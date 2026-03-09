"""
Slack API fetcher for cppa_slack_tracker.

All functions use the Slack client from operations.slack_ops (REST requests only).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from operations.slack_ops.tokens import get_slack_client

logger = logging.getLogger(__name__)


def fetch_user_list(
    _team_id: str,
    *,
    client=None,
) -> list[dict]:
    """
    Fetch all team members for the workspace (team_id).
    The bot token is scoped to one workspace; team_id is for consistency.
    Returns list of member dicts (id, name, real_name, profile, ...).
    """
    if client is None:
        client = get_slack_client(team_id=_team_id)
    members = []
    cursor = None
    while True:
        data = client.users_list(
            limit=1000,
            cursor=cursor,
        )
        if not data.get("ok"):
            logger.warning("users.list failed: %s", data.get("error", "unknown"))
            break
        members.extend(data.get("members", []))
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return members


def fetch_user_info(
    user_id: str,
    *,
    client=None,
    team_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Fetch detailed user info for user_id.
    Returns the Slack user object (id, name, real_name, profile, ...) or None on error.
    """
    if client is None:
        client = get_slack_client(team_id=team_id)
    data = client.users_info(user_id)
    if not data.get("ok"):
        logger.warning(
            "users.info failed for %s: %s",
            user_id,
            data.get("error", "unknown"),
        )
        return None
    return data.get("user")


def fetch_team_info(
    team_id: Optional[str] = None,
    *,
    client=None,
) -> Optional[dict]:
    """
    Fetch workspace/team info (team the bot token belongs to).
    Returns the Slack team object (id, name, ...) or None on error.
    Tries team.info first; if that fails (e.g. missing team:read scope),
    falls back to auth.test which returns team name without extra scope.
    """
    if client is None:
        client = get_slack_client(team_id=team_id)
    data = client.team_info()
    if data.get("ok"):
        team = data.get("team")
        if team and (team.get("name") or team.get("id")):
            if not team_id or team.get("id") == team_id:
                return team
    logger.debug(
        "team.info failed or no name: %s; trying auth.test",
        data.get("error", "no team name"),
    )
    auth = client.auth_test()
    if not auth.get("ok"):
        logger.warning("auth.test failed: %s", auth.get("error", "unknown"))
        return None
    # auth.test returns "team" (workspace name) and "team_id"
    tid = auth.get("team_id") or ""
    tname = (auth.get("team") or "").strip() or tid
    if team_id and tid != team_id:
        return None
    return {"id": tid, "name": tname}


def fetch_channel_list(
    _team_id: str,
    *,
    types: str = "public_channel",
    exclude_archived: bool = False,
    client=None,
) -> list[dict]:
    """
    Fetch channel list for the workspace (team_id).
    The bot token is scoped to one workspace. Returns list of channel dicts (id, name, ...).
    """
    if client is None:
        client = get_slack_client(team_id=_team_id)
    channels = []
    cursor = None
    while True:
        data = client.conversations_list(
            types=types,
            exclude_archived=exclude_archived,
            limit=500,
            cursor=cursor,
        )
        if not data.get("ok"):
            logger.warning(
                "conversations.list failed: %s", data.get("error", "unknown")
            )
            break
        channels.extend(data.get("channels", []))
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return channels


def _ts_to_utc_date(ts: Optional[str]) -> Optional[date]:
    """Convert Slack ts string to UTC date, or None if invalid."""
    if not ts:
        return None
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.date()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def fetch_messages(
    channel_id: str,
    start_date: date | datetime | None,
    end_date: date | datetime,
    *,
    client=None,
    team_id: Optional[str] = None,
) -> list[dict]:
    """
    Fetch all messages for a channel.

    When start_date is set: messages in [start_date, end_date] (inclusive, UTC).
    When start_date is None: all messages up to end_date (API called without oldest,
    so from the beginning of the channel). Uses conversations.history, then filters
    by created or edited date.
    """
    if client is None:
        client = get_slack_client(team_id=team_id)
    if isinstance(end_date, datetime):
        end_date = end_date.astimezone(timezone.utc).date()
    if start_date is not None:
        if isinstance(start_date, datetime):
            start_date = start_date.astimezone(timezone.utc).date()
        range_start = datetime(
            start_date.year,
            start_date.month,
            start_date.day,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        )
        oldest_ts: Optional[str] = str(range_start.timestamp())
    else:
        oldest_ts = None

    range_end = datetime(
        end_date.year,
        end_date.month,
        end_date.day,
        23,
        59,
        59,
        999999,
        tzinfo=timezone.utc,
    )
    latest_ts = str(range_end.timestamp())
    messages = []
    cursor = None
    while True:
        kwargs = {
            "channel": channel_id,
            "limit": 1000,
            "latest": latest_ts,
            "cursor": cursor,
        }
        if oldest_ts is not None:
            kwargs["oldest"] = oldest_ts
        data = client.conversations_history(**kwargs)
        if not data.get("ok"):
            logger.warning(
                "conversations.history failed for %s: %s",
                channel_id,
                data.get("error", "unknown"),
            )
            break
        batch = data.get("messages", [])
        for msg in batch:
            created_d = _ts_to_utc_date(msg.get("ts"))
            if start_date is not None:
                if created_d and start_date <= created_d <= end_date:
                    messages.append(msg)
                    continue
                edited = msg.get("edited") or {}
                edited_d = _ts_to_utc_date(edited.get("ts"))
                if edited_d and start_date <= edited_d <= end_date:
                    messages.append(msg)
            else:
                if created_d and created_d <= end_date:
                    messages.append(msg)
                    continue
                edited = msg.get("edited") or {}
                edited_d = _ts_to_utc_date(edited.get("ts"))
                if edited_d and edited_d <= end_date:
                    messages.append(msg)
        if not batch:
            break
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return messages


def fetch_channel_user_list(
    channel_id: str,
    *,
    client=None,
    team_id: Optional[str] = None,
) -> list[str]:
    """
    Fetch the list of user IDs that are members of the channel.
    Returns list of Slack user IDs (strings).
    """
    if client is None:
        client = get_slack_client(team_id=team_id)
    user_ids = []
    cursor = None
    while True:
        data = client.conversations_members(
            channel=channel_id,
            limit=1000,
            cursor=cursor,
        )
        if not data.get("ok"):
            error = data.get("error", "unknown")
            logger.warning(
                "conversations.members failed for %s: %s",
                channel_id,
                error,
            )
            raise RuntimeError(
                f"conversations.members failed for channel_id={channel_id}: {error}"
            )
        user_ids.extend(data.get("members", []))
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return user_ids
