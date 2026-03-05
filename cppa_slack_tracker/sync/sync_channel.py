"""
Sync Slack channels with the database.

Fetches channels via cppa_slack_tracker.fetcher.fetch_channel_list (or
conversations.info for a single channel_id) and syncs to the database.
"""

from __future__ import annotations

import logging
from typing import Optional

from cppa_slack_tracker.fetcher import fetch_channel_list, fetch_team_info
from cppa_slack_tracker.models import SlackTeam
from cppa_slack_tracker.services import (
    get_or_create_slack_channel,
    get_or_create_slack_team,
)

logger = logging.getLogger(__name__)


def sync_team(team_id: str, team_name: Optional[str] = None) -> SlackTeam:
    """Get or create a SlackTeam by team_id. Fetches real team name from API when missing or same as team_id."""
    name = (team_name or "").strip() or None
    if not name or name == team_id:
        try:
            team_data = fetch_team_info(team_id)
        except Exception:
            logger.exception("Failed to fetch team info for team_id=%s", team_id)
            team_data = None
        if team_data:
            fetched_id = team_data.get("id") or team_id
            if fetched_id == team_id:
                name = (team_data.get("name") or "").strip() or team_id
            else:
                name = name or team_id
        else:
            name = name or team_id
    return get_or_create_slack_team(
        {
            "team_id": team_id,
            "team_name": name,
        }
    )[0]


def _process_channel_info(ch: dict, team: SlackTeam) -> bool:
    """
    Process one channel: get_or_create_slack_channel. Returns True if synced,
    False if skipped (missing id or non-public channel). Raises on error.
    """
    if not ch.get("id"):
        return False
    channel, _ = get_or_create_slack_channel(ch, team)
    return channel is not None


def sync_channels(
    team: SlackTeam,
    *,
    channel_id: Optional[str] = None,
    team_id: Optional[str] = None,
    types: str = "public_channel",
    exclude_archived: bool = False,
) -> tuple[int, int]:
    """
    Sync channels for a team to the database.

    If channel_id is set, fetch only that channel (conversations.info).
    Otherwise fetch via fetch_channel_list(team_id). Returns (success_count, error_count).
    """
    success_count = 0
    error_count = 0

    # Single channel: fetch from API only
    if channel_id:
        from operations.slack_ops.tokens import get_slack_client

        tid = team_id or team.team_id
        try:
            data = get_slack_client(team_id=tid).conversations_info(channel=channel_id)
        except Exception:
            logger.exception("conversations.info raised for channel_id=%s", channel_id)
            return 0, 1
        if not data.get("ok"):
            logger.warning(
                "conversations.info failed: %s", data.get("error", "unknown")
            )
            return 0, 1
        ch = data.get("channel", {})
        try:
            if _process_channel_info(ch, team):
                return 1, 0
            return 0, 0
        except Exception as e:
            logger.warning("Failed to sync channel %s: %s", channel_id, e)
            return 0, 1

    # Fetch from API
    try:
        channels = fetch_channel_list(
            team_id or team.team_id,
            types=types,
            exclude_archived=exclude_archived,
        )
    except Exception:
        logger.exception(
            "Failed to fetch channels for team_id=%s", team_id or team.team_id
        )
        return success_count, error_count + 1
    for ch in channels:
        if not isinstance(ch, dict):
            logger.warning("Skipping malformed channel payload: %r", ch)
            error_count += 1
            continue
        try:
            if _process_channel_info(ch, team):
                success_count += 1
        except Exception as e:
            ch_id = ch.get("id") if isinstance(ch, dict) else None
            logger.warning("Failed to sync channel %s: %s", ch_id, e)
            error_count += 1
    return success_count, error_count
