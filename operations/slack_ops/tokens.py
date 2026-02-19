"""
Slack token resolution: get bot or app token from Django settings or env.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def get_slack_bot_token() -> str:
    """
    Return SLACK_BOT_TOKEN from Django settings or os.environ.
    Raises ValueError if not set.
    """
    try:
        from django.conf import settings

        token = getattr(settings, "SLACK_BOT_TOKEN", None) or ""
    except Exception:
        token = ""
    if not token:
        token = os.environ.get("SLACK_BOT_TOKEN", "")
    token = (token or "").strip()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is not set. Set it in Django settings or SLACK_BOT_TOKEN env.")
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
        raise ValueError("SLACK_APP_TOKEN is not set. Set it in Django settings or SLACK_APP_TOKEN env.")
    return token


def get_slack_client(bot_token: Optional[str] = None) -> "SlackAPIClient":
    """Get a SlackAPIClient with the given token or SLACK_BOT_TOKEN from settings."""
    from operations.slack_ops.client import SlackAPIClient

    token = (bot_token or "").strip() or get_slack_bot_token()
    logger.debug("Creating Slack API client")
    return SlackAPIClient(token)
