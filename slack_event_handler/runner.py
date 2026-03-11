"""
Slack Event Handler runner.
Runs the unified Slack listener (huddle transcript tracking + Slack PR comment bot).
Supports multiple teams: one listener per team in SLACK_BOT_TOKEN, each in its own thread.
"""

import logging
import threading

from django.conf import settings

from slack_event_handler.workspace import get_workspace_root
from operations.slack_ops import get_slack_app_token, get_slack_bot_token

logger = logging.getLogger(__name__)


def run_slack_event_handler(bot_token=None, app_token=None):
    """
    Main entry point for the unified Slack Event Handler.
    If multiple teams are configured (SLACK_TEAMS + SLACK_BOT_TOKEN_<id>), starts one
    listener per team in a separate thread. Otherwise uses default team key (single/first in SLACK_TEAMS).
    """
    try:
        root = get_workspace_root()
        logger.debug("Slack Event Handler workspace root: %s", root)
    except Exception as e:
        logger.exception("Failed to resolve workspace root: %s", e)

    try:
        app_token = (app_token or "").strip() or get_slack_app_token()
    except ValueError:
        app_token = None
    if not app_token:
        logger.error(
            "Missing SLACK_APP_TOKEN in .env file. "
            "To get App Token: api.slack.com/apps > Your App > Basic Information > "
            "App-Level Tokens > Generate token with 'connections:write' scope"
        )
        return

    tokens_map = getattr(settings, "SLACK_BOT_TOKEN", None) or {}
    if not isinstance(tokens_map, dict):
        tokens_map = {}

    if tokens_map:
        # Multiple (or single) teams from SLACK_TEAMS + SLACK_BOT_TOKEN_<id>
        from slack_event_handler.utils.slack_listener import start_slack_listener

        started = 0
        for team_id, token in tokens_map.items():
            token = (token or "").strip()
            if not token:
                continue
            logger.info("Starting Slack Event Listener for team=%s", team_id)
            t = threading.Thread(
                target=start_slack_listener,
                kwargs={"bot_token": token, "app_token": app_token, "team_id": team_id},
                daemon=True,
                name=f"slack-listener-{team_id}",
            )
            t.start()
            started += 1
        if started == 0:
            logger.error("No valid SLACK_BOT_TOKEN_<team_id> in .env")
    else:
        # Single team: use default key from SLACK_TEAMS (only key or first key)
        from operations.slack_ops import get_default_team_key
        from slack_event_handler.utils.slack_listener import start_slack_listener

        team_id = get_default_team_key() or None
        try:
            token = (bot_token or "").strip() or get_slack_bot_token(team_id=team_id)
        except ValueError:
            token = None
        if not token:
            logger.error(
                "Missing SLACK_BOT_TOKEN in .env file (set SLACK_TEAMS and SLACK_BOT_TOKEN_<id>)"
            )
            return
        logger.info(
            "Starting Slack Event Listener for team=%s", team_id or "default"
        )
        start_slack_listener(bot_token=token, app_token=app_token, team_id=team_id)
