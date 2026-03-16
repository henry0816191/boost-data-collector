"""
Management command: run_slack_event_handler

Runs the unified Slack Event Handler: huddle AI note transcript tracking and
Slack PR comment bot, both in a single Socket Mode listener.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from operations.slack_ops import (
    get_slack_app_token,
    get_slack_bot_token,
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
                "Only validate that SLACK_BOT_TOKEN_<id> and SLACK_APP_TOKEN_<id> are set per team; "
                "do not start the listener."
            ),
        )

    def handle(self, *args, **options):
        tokens_map = getattr(settings, "SLACK_BOT_TOKEN", None) or {}
        if not isinstance(tokens_map, dict):
            tokens_map = {}
        team_ids = list(tokens_map.keys()) if tokens_map else []

        bot_results = []
        app_results = []
        for tid in team_ids:
            try:
                bot_token = get_slack_bot_token(team_id=tid)
                bot_results.append((tid, bool(bot_token)))
            except ValueError:
                bot_results.append((tid, False))
            try:
                app_token = get_slack_app_token(team_id=tid)
                app_results.append((tid, bool(app_token)))
            except ValueError:
                app_results.append((tid, False))

        if options["dry_run"]:
            for tid in team_ids:
                bot_ok = next((r for t, r in bot_results if t == tid), False)
                app_ok = next((r for t, r in app_results if t == tid), False)
                if bot_ok:
                    logger.info("SLACK_BOT_TOKEN_%s is set", tid)
                else:
                    logger.warning("SLACK_BOT_TOKEN_%s is not set", tid)
                if app_ok:
                    logger.info("SLACK_APP_TOKEN_%s is set", tid)
                else:
                    logger.warning("SLACK_APP_TOKEN_%s is not set", tid)
            if not team_ids:
                logger.warning(
                    "No teams configured (set SLACK_TEAM_IDS and SLACK_BOT_TOKEN_<id>)"
                )
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
