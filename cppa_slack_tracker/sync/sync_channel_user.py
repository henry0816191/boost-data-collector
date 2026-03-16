"""
Sync Slack channel memberships with the database.

Fetches channel member lists via cppa_slack_tracker.fetcher.fetch_channel_user_list
and syncs memberships to the database. Use get_channels_to_sync() to get the list
of channels to sync (one or all in a team); run_cppa_slack_tracker uses it to
avoid duplicating channel resolution logic.
"""

from __future__ import annotations

import logging
from typing import Optional

from cppa_slack_tracker.fetcher import fetch_channel_user_list
from cppa_slack_tracker.models import SlackChannel, SlackTeam
from cppa_slack_tracker.services import sync_channel_memberships

logger = logging.getLogger(__name__)


def get_channels_to_sync(
    team: SlackTeam,
    *,
    channel_id: Optional[str] = None,
) -> list[SlackChannel]:
    """
    Return the list of channels to sync for a team.

    If channel_id is set and exists, returns that single channel; if not found,
    logs a warning and returns all channels in the team. If channel_id is not
    set, returns all channels in the team ordered by channel_id.
    """
    if channel_id:
        try:
            return [SlackChannel.objects.get(team=team, channel_id=channel_id)]
        except SlackChannel.DoesNotExist:
            logger.warning(
                "Channel %s not found in team %s; syncing all channels in team.",
                channel_id,
                team.team_id,
            )
    return list(SlackChannel.objects.filter(team=team).order_by("channel_id"))


def sync_channel_users(
    team: SlackTeam,
    *,
    channel_id: Optional[str] = None,
) -> tuple[int, int]:
    """
    Sync channel memberships for all (or one) channels in a team.

    Uses get_channels_to_sync(team, channel_id=channel_id) to get the channel
    list, then for each channel fetches member IDs from the Slack API and
    syncs memberships to the database. Returns (success_count, error_count).
    """
    channels = get_channels_to_sync(team, channel_id=channel_id)
    success_count = 0
    error_count = 0
    for channel in channels:
        try:
            member_ids = fetch_channel_user_list(
                channel.channel_id, team_id=channel.team.team_id
            )
            sync_channel_memberships(channel, member_ids)
            success_count += 1
        except Exception as e:
            logger.exception(
                "Failed to fetch/sync members for %s: %s", channel.channel_id, e
            )
            error_count += 1
    return success_count, error_count
