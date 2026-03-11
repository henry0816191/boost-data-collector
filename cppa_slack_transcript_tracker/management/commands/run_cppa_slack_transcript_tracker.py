"""
Management command: run_cppa_slack_transcript_tracker

Runs the CPPA Slack Transcript Tracker (Slack listener + huddle processing).
All functionality lives in this app.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from operations.slack_ops import get_slack_app_token, get_slack_bot_token

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run CPPA Slack Transcript Tracker: listen for huddle AI note events and process them. "
        "Uses cppa_slack_transcript_tracker.utils and runner."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only check that SLACK_BOT_TOKEN and SLACK_APP_TOKEN are set; do not start the listener.",
        )

    def handle(self, *args, **options):
        try:
            team_id = getattr(settings, "SLACK_TEAM_ID", None) or None
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
            logger.info("Would start Slack Event Listener (Socket Mode).")
            return

        logger.info("Starting CPPA Slack Transcript Tracker (in-app runner)...")
        try:
            from cppa_slack_transcript_tracker.runner import run_slack_huddle

            run_slack_huddle()
        except KeyboardInterrupt:
            logger.info("Stopped by user (Ctrl+C).")
        except Exception as e:
            logger.exception("run_cppa_slack_transcript_tracker: %s", e)
            raise
