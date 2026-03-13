"""
Slack token resolution: get bot or app token from Django settings or env.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from operations.slack_ops.client import SlackAPIClient

logger = logging.getLogger(__name__)


def _slack_team_fallback() -> str:
    """Return default team key from SLACK_TEAM_ID. Raises ValueError if not set."""
    try:
        from django.conf import settings as django_settings

        team_id = (getattr(django_settings, "SLACK_TEAM_ID", "") or "").strip()
    except Exception:
        team_id = ""
    if not team_id:
        logger.error(
            "SLACK_TEAM_ID is not set. Set SLACK_TEAM_ID in .env (must match a key in SLACK_TEAM_IDS)."
        )
        raise ValueError(
            "SLACK_TEAM_ID is required for default team. Set SLACK_TEAM_ID in .env."
        )
    return team_id


def get_default_team_key() -> str:
    """Return the default team key from SLACK_TEAM_ID. Raises ValueError if not set."""
    return _slack_team_fallback()


def get_slack_bot_token(team_id: Optional[str] = None) -> str:
    """
    Return the Slack bot token for the given team (team_id).

    SLACK_BOT_TOKEN in settings is a dict (team_id -> token), built from env via
    SLACK_TEAM_IDS and SLACK_BOT_TOKEN_<id>. When team_id is missing or empty,
    falls back to the default team key (single or first in SLACK_TEAM_IDS).
    Logs error and raises ValueError only if both team_id and fallback are absent,
    or the token for that team is missing.
    """
    tid = (team_id or "").strip()
    if not tid:
        tid = _slack_team_fallback()
    if not tid:
        logger.error("team id is missing for Slack bot token lookup")
        raise ValueError("team id is required for get_slack_bot_token")

    try:
        from django.conf import settings

        tokens_map = getattr(settings, "SLACK_BOT_TOKEN", None)
    except Exception:
        tokens_map = None

    if not isinstance(tokens_map, dict) or tid not in tokens_map:
        logger.error(
            "team %s is missing from SLACK_BOT_TOKEN. Set SLACK_TEAM_IDS and SLACK_BOT_TOKEN_%s in .env",
            tid,
            tid,
        )
        raise ValueError(
            f"team {tid!r} not found in SLACK_BOT_TOKEN. "
            f"Add {tid!r} to SLACK_TEAM_IDS and set SLACK_BOT_TOKEN_{tid} in .env"
        )

    token = (tokens_map[tid] or "").strip()
    if not token:
        logger.error("token for team %s is missing in SLACK_BOT_TOKEN", tid)
        raise ValueError(f"token for team {tid!r} is missing in SLACK_BOT_TOKEN")

    return token


def get_slack_app_token(team_id: Optional[str] = None) -> str:
    """
    Return the Slack app token for the given team (team_id).

    SLACK_APP_TOKEN in settings is a dict (team_id -> token), built from env via
    SLACK_TEAM_IDS and SLACK_APP_TOKEN_<id>. When team_id is missing or empty,
    falls back to the default team key (single or first in SLACK_TEAM_IDS).
    Raises ValueError if the token for that team is not set.
    """
    tid = (team_id or "").strip()
    if not tid:
        tid = _slack_team_fallback()
    if not tid:
        logger.error("team id is missing for Slack app token lookup")
        raise ValueError("team id is required for get_slack_app_token")

    try:
        from django.conf import settings

        tokens_map = getattr(settings, "SLACK_APP_TOKEN", None)
    except Exception:
        tokens_map = None

    if not isinstance(tokens_map, dict) or tid not in tokens_map:
        logger.error(
            "team %s is missing from SLACK_APP_TOKEN. Set SLACK_TEAM_IDS and SLACK_APP_TOKEN_%s in .env",
            tid,
            tid,
        )
        raise ValueError(
            f"team {tid!r} not found in SLACK_APP_TOKEN. "
            f"Add {tid!r} to SLACK_TEAM_IDS and set SLACK_APP_TOKEN_{tid} in .env"
        )

    token = (tokens_map[tid] or "").strip()
    if not token:
        logger.error("token for team %s is missing in SLACK_APP_TOKEN", tid)
        raise ValueError(f"token for team {tid!r} is missing in SLACK_APP_TOKEN")

    return token


def get_slack_client(
    bot_token: Optional[str] = None, team_id: Optional[str] = None
) -> "SlackAPIClient":
    """
    Get a SlackAPIClient with the given token, or the token for team_id from
    settings.SLACK_BOT_TOKEN (dict). When neither bot_token nor team_id is
    provided, get_slack_bot_token(team_id) uses the default team key (from SLACK_TEAM_IDS) internally.
    """
    from operations.slack_ops.client import SlackAPIClient

    token = (bot_token or "").strip() or get_slack_bot_token(team_id)
    logger.debug("Creating Slack API client")
    return SlackAPIClient(token)
