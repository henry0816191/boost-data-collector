"""
Sync Slack channel memberships with the database.

If workspace/cppa_slack_tracker/<team_slug>/<channel_slug>/members.json exists,
process it (list of user IDs) then remove the file. Otherwise fetch member IDs
via cppa_slack_tracker.fetcher.fetch_channel_user_list and sync.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from cppa_slack_tracker.fetcher import fetch_channel_user_list
from cppa_slack_tracker.models import SlackChannel, SlackTeam
from cppa_slack_tracker.services import sync_channel_memberships
from cppa_slack_tracker.workspace import get_members_json_path

logger = logging.getLogger(__name__)


def _process_channel_members(channel: SlackChannel, member_ids: list[str]) -> None:
    """Sync channel memberships to match member_ids. Raises on error."""
    sync_channel_memberships(channel, member_ids)


def sync_channel_members(channel: SlackChannel) -> bool:
    """
    Sync memberships for one channel.

    First checks workspace/cppa_slack_tracker/<team_slug>/<channel_slug>/members.json.
    If it exists, loads it (list of user IDs), syncs memberships, then removes the
    file. If not, fetches via fetch_channel_user_list from cppa_slack_tracker.fetcher.

    Returns True if sync succeeded, False otherwise.
    """
    team_slug = channel.team.team_name
    channel_slug = channel.channel_name
    members_path = get_members_json_path(team_slug, channel_slug)

    members_from_file = None
    if members_path.exists():
        try:
            data = json.loads(members_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                members_from_file = data
            else:
                logger.warning(
                    "Unexpected format in %s (not a list); removing file",
                    members_path,
                )
                try:
                    members_path.unlink()
                except OSError as unlink_e:
                    logger.warning("Failed to remove %s: %s", members_path, unlink_e)
        except Exception as e:
            logger.exception("Failed to load %s: %s", members_path, e)
            try:
                members_path.unlink()
            except OSError as unlink_e:
                logger.warning("Failed to remove %s: %s", members_path, unlink_e)

        if members_from_file is not None:
            member_ids = [
                m.strip() for m in members_from_file if isinstance(m, str) and m.strip()
            ]
            if len(member_ids) != len(members_from_file):
                logger.warning(
                    "Invalid members payload in %s: expected non-empty list[str]; removing file",
                    members_path,
                )
            else:
                try:
                    _process_channel_members(channel, member_ids)
                except Exception as e:
                    logger.warning(
                        "Failed to sync members for %s: %s",
                        channel.channel_id,
                        e,
                    )

            try:
                members_path.unlink()
            except OSError as e:
                logger.exception("Failed to remove %s: %s", members_path, e)

    # No members.json or load failed: fetch from API
    try:
        member_ids = fetch_channel_user_list(channel.channel_id)
        _process_channel_members(channel, member_ids)
        return True
    except Exception as e:
        logger.exception(
            "Failed to fetch/sync members for %s: %s", channel.channel_id, e
        )
        return False


def sync_channel_users(
    team: SlackTeam,
    *,
    channel_id: Optional[str] = None,
) -> tuple[int, int]:
    """
    Sync channel memberships for all (or one) channels in a team.

    If channel_id is set, sync only that channel; otherwise sync all channels
    in the team. Returns (success_count, error_count).
    """
    if channel_id:
        try:
            channels = [SlackChannel.objects.get(team=team, channel_id=channel_id)]
        except SlackChannel.DoesNotExist:
            logger.warning("Channel %s not found in team %s", channel_id, team.team_id)
            channels = list(SlackChannel.objects.filter(team=team))
    else:
        channels = list(SlackChannel.objects.filter(team=team))
    success_count = 0
    error_count = 0
    for channel in channels:
        if sync_channel_members(channel):
            success_count += 1
        else:
            error_count += 1
    return success_count, error_count
