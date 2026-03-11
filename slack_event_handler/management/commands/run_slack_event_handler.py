"""
Management command: run_slack_event_handler

Runs the unified Slack Event Handler: huddle AI note transcript tracking and
Slack PR comment bot, both in a single Socket Mode listener.
"""

import logging

from django.core.management.base import BaseCommand

from operations.slack_ops import (
    get_slack_app_token,
    get_slack_bot_token,
    get_default_team_key,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run the unified Slack Event Handler: listens for huddle AI note events "
        "(transcript tracking) and GitHub PR URL messages (Slack PR comment bot)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Only validate that SLACK_BOT_TOKEN and SLACK_APP_TOKEN are set; "
                "do not start the listener."
            ),
        )

    def handle(self, *args, **options):
        try:
            team_id = get_default_team_key() or None
            bot_token = get_slack_bot_token(team_id=team_id)
        except ValueError:
            bot_token = None
        try:
            app_token = get_slack_app_token()
        except ValueError:
            app_token = None

        if options["dry_run"]:
            if bot_token:
                logger.info("SLACK_BOT_TOKEN is set")
            else:
                logger.warning("SLACK_BOT_TOKEN is not set")
            if app_token:
                logger.info("SLACK_APP_TOKEN is set")
            else:
                logger.warning("SLACK_APP_TOKEN is not set")
            logger.info("Would start unified Slack Event Handler (Socket Mode).")
            return

        logger.info("Starting unified Slack Event Handler...")
        try:
            from slack_event_handler.runner import run_slack_event_handler

            run_slack_event_handler()
        except KeyboardInterrupt:
            logger.info("Stopped by user (Ctrl+C).")
        except Exception as e:
            logger.exception("run_slack_event_handler: %s", e)
            raise
