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
    If multiple teams are configured (SLACK_TEAM_IDS + SLACK_BOT_TOKEN_<id>), starts one
    listener per team in a separate thread. Otherwise uses default team key (single/first in SLACK_TEAM_IDS).
    """
    try:
        root = get_workspace_root()
        logger.debug("Slack Event Handler workspace root: %s", root)
    except Exception as e:
        logger.exception("Failed to resolve workspace root: %s", e)

    tokens_map = getattr(settings, "SLACK_BOT_TOKEN", None) or {}
    if not isinstance(tokens_map, dict):
        tokens_map = {}

    if tokens_map:
        # Multiple (or single) teams from SLACK_TEAM_IDS + SLACK_BOT_TOKEN_<id> and SLACK_APP_TOKEN_<id>
        from slack_event_handler.utils.slack_listener import start_slack_listener

        listeners = []
        started = 0
        for team_id, token in tokens_map.items():
            token = (token or "").strip()
            if not token:
                continue
            try:
                team_app_token = (app_token or "").strip() or get_slack_app_token(
                    team_id
                )
            except ValueError:
                logger.warning(
                    "Skipping team %s: SLACK_APP_TOKEN_%s not set in .env",
                    team_id,
                    team_id,
                )
                continue
            logger.info("Starting Slack Event Listener for team=%s", team_id)
            t = threading.Thread(
                target=start_slack_listener,
                kwargs={
                    "bot_token": token,
                    "app_token": team_app_token,
                    "team_id": team_id,
                },
                daemon=True,
                name=f"slack-listener-{team_id}",
            )
            t.start()
            listeners.append(t)
            started += 1
        if started == 0:
            logger.error(
                "No valid team with both SLACK_BOT_TOKEN_<id> and SLACK_APP_TOKEN_<id> in .env"
            )
        else:
            for t in listeners:
                t.join()
    else:
        # Single team: use default key from SLACK_TEAM_IDS (only key or first key)
        from operations.slack_ops import get_default_team_key
        from slack_event_handler.utils.slack_listener import start_slack_listener

        team_id = get_default_team_key() or None
        try:
            token = (bot_token or "").strip() or get_slack_bot_token(team_id=team_id)
        except ValueError:
            token = None
        try:
            app_token = (app_token or "").strip() or get_slack_app_token(team_id)
        except ValueError:
            app_token = None
        if not token:
            logger.error(
                "Missing SLACK_BOT_TOKEN in .env file (set SLACK_TEAM_IDS and SLACK_BOT_TOKEN_<id>)"
            )
            return
        if not app_token:
            logger.error(
                "Missing SLACK_APP_TOKEN_<id> in .env file. Set SLACK_TEAM_IDS and SLACK_APP_TOKEN_<id> for the default team."
            )
            return
        logger.info("Starting Slack Event Listener for team=%s", team_id or "default")
        start_slack_listener(bot_token=token, app_token=app_token, team_id=team_id)
