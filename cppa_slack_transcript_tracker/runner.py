"""
CPPA Slack Transcript Tracker runner.
Runs the Slack listener and huddle processing logic.
"""

import logging

from django.conf import settings

from cppa_slack_transcript_tracker.workspace import (
    get_workspace_root,
    set_working_directory,
)
from operations.slack_ops import get_slack_app_token, get_slack_bot_token

logger = logging.getLogger(__name__)


def run_slack_huddle(bot_token=None, app_token=None):
    """
    Main entry point for Slack Huddle Processor.
    Validates tokens, then starts the listener.
    Uses the app workspace directory (workspace/cppa_slack_transcript_tracker) for data/ and temp files.
    """
    try:
        root = get_workspace_root()
        set_working_directory()
        logger.debug("CPPA Slack Transcript Tracker working directory: %s", root)
    except Exception as e:
        logger.exception(
            "Failed to resolve workspace root or set working directory: %s", e
        )

    try:
        team_id = (getattr(settings, "SLACK_TEAM_ID", None) or "").strip() or None
        token = (bot_token or "").strip()
        bot_token = token or get_slack_bot_token(team_id=team_id)
    except ValueError:
        bot_token = None
    try:
        app_token = app_token or get_slack_app_token()
    except ValueError:
        app_token = None

    if not bot_token:
        error_msg = "Missing SLACK_BOT_TOKEN in .env file"
        logger.error(error_msg)
        return

    if not app_token:
        error_msg = "Missing SLACK_APP_TOKEN in .env file"
        logger.error(error_msg)
        logger.error(
            "To get App Token: api.slack.com/apps > Your App > Basic Information > "
            "App-Level Tokens > Generate token with 'connections:write' scope"
        )
        return

    logger.debug("Starting Slack Event Listener")
    from cppa_slack_transcript_tracker.utils.slack_listener import start_slack_listener

    start_slack_listener(bot_token=bot_token, app_token=app_token)
