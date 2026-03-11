"""
Slack token resolution: get bot or app token from Django settings or env.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from operations.slack_ops.client import SlackAPIClient

logger = logging.getLogger(__name__)


def _slack_team_id_fallback() -> str:
    """Return SLACK_TEAM_ID from Django settings or os.environ for single-workspace fallback."""
    try:
        from django.conf import settings as django_settings

        tid = (getattr(django_settings, "SLACK_TEAM_ID", None) or "").strip()
    except Exception:
        tid = ""
    if not tid:
        tid = (os.environ.get("SLACK_TEAM_ID") or "").strip()
    return tid


def get_slack_bot_token(team_id: Optional[str] = None) -> str:
    """
    Return the Slack bot token for the given workspace (team_id).

    SLACK_BOT_TOKEN in settings is a dict (team_id -> token), built from env via
    SLACK_TEAM_IDS and SLACK_BOT_TOKEN_<team_id>. When team_id is missing or empty,
    falls back to SLACK_TEAM_ID from Django settings or os.environ so single-workspace
    setups (e.g. cppa_slack_transcript_tracker) work without passing team_id.
    Logs error and raises ValueError only if both team_id and fallback are absent,
    or the token for that team is missing.
    """
    tid = (team_id or "").strip()
    if not tid:
        tid = _slack_team_id_fallback()
    if not tid:
        logger.error("team_id is missing for Slack bot token lookup")
        raise ValueError("team_id is required for get_slack_bot_token")

    try:
        from django.conf import settings

        tokens_map = getattr(settings, "SLACK_BOT_TOKEN", None)
    except Exception:
        tokens_map = None

    if not isinstance(tokens_map, dict) or tid not in tokens_map:
        logger.error(
            "team_id %s is missing from SLACK_BOT_TOKEN. Set SLACK_TEAM_IDS and SLACK_BOT_TOKEN_%s in .env",
            tid,
            tid,
        )
        raise ValueError(
            f"team_id {tid!r} not found in SLACK_BOT_TOKEN. "
            f"Add {tid!r} to SLACK_TEAM_IDS and set SLACK_BOT_TOKEN_{tid} in .env"
        )

    token = (tokens_map[tid] or "").strip()
    if not token:
        logger.error("token for team_id %s is missing in SLACK_BOT_TOKEN", tid)
        raise ValueError(f"token for team_id {tid!r} is missing in SLACK_BOT_TOKEN")

    return token


def get_slack_app_token() -> str:
    """
    Return SLACK_APP_TOKEN from Django settings or os.environ.
    Raises ValueError if not set.
    """
    try:
        from django.conf import settings

        token = getattr(settings, "SLACK_APP_TOKEN", None) or ""
    except Exception:
        token = ""
    if not token:
        token = os.environ.get("SLACK_APP_TOKEN", "")
    token = (token or "").strip()
    if not token:
        raise ValueError(
            "SLACK_APP_TOKEN is not set. Set it in Django settings or SLACK_APP_TOKEN env."
        )
    return token


def get_slack_client(
    bot_token: Optional[str] = None, team_id: Optional[str] = None
) -> "SlackAPIClient":
    """
    Get a SlackAPIClient with the given token, or the token for team_id from
    settings.SLACK_BOT_TOKEN (dict). When neither bot_token nor team_id is
    provided, get_slack_bot_token(team_id) uses SLACK_TEAM_ID fallback internally.
    """
    from operations.slack_ops.client import SlackAPIClient

    token = (bot_token or "").strip() or get_slack_bot_token(team_id)
    logger.debug("Creating Slack API client")
    return SlackAPIClient(token)
