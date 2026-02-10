"""Run all collector commands in order (see docs/Workflow.md)."""

import logging
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

# Order matters — see docs/Workflow.md
COLLECTOR_COMMANDS = [
    "run_boost_library_tracker",
    "run_discord_exporter",
    # Add more as apps are added: run_boost_usage_tracker, etc.
]


class Command(BaseCommand):
    help = "Run all collector commands in order. Exit 0 only if all succeed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--stop-on-failure",
            action="store_true",
            help="Stop running remaining collectors after the first failure.",
        )

    def handle(self, *args, **options):
        stop_on_failure = options["stop_on_failure"]
        results = []
        exit_code = 0

        logger.info(
            "run_all_collectors: starting (%d commands)",
            len(COLLECTOR_COMMANDS),
        )

        for name in COLLECTOR_COMMANDS:
            self.stdout.write(f"Running {name}...")
            try:
                call_command(name)
                results.append((name, 0))
                self.stdout.write(self.style.SUCCESS(f"  {name}: success"))
            except CommandError as e:
                code = getattr(e, "returncode", 1) or 1
                results.append((name, code))
                logger.error("%s failed: %s", name, e)
                exit_code = code
                if stop_on_failure:
                    break
            except Exception as e:
                logger.exception("%s failed: %s", name, e)
                results.append((name, -1))
                exit_code = 1
                if stop_on_failure:
                    break

        succeeded = sum(1 for _, code in results if code == 0)
        failed = len(results) - succeeded
        logger.info(
            "run_all_collectors: finished; succeeded=%d, failed=%d",
            succeeded,
            failed,
        )
        self.stdout.write(
            self.style.WARNING(
                f"Summary: {succeeded} succeeded, {failed} failed."
            )
        )

        if exit_code != 0:
            sys.exit(exit_code)
