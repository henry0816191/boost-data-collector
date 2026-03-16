"""
Management command: check_new_boost_release
Exits 0 if a new Boost release exists (GitHub API has a release not in BoostVersion), else 1.
Used by automation (e.g. boost_collector_runner) to decide whether to run on_release tasks.
"""

import sys

from django.core.management.base import BaseCommand

from boost_library_tracker.release_check import has_new_boost_release


class Command(BaseCommand):
    """Exit 0 if a new Boost release exists (not in BoostVersion), else 1; for scheduler/automation."""

    help = (
        "Exit 0 if a new Boost release exists (not yet in BoostVersion), else 1. "
        "Used by schedulers to run on_release tasks only when a new release is available."
    )

    def handle(self, *args, **options):
        """Check for new Boost release; exit 0 if found, 1 otherwise."""
        if has_new_boost_release():
            self.stdout.write(self.style.SUCCESS("New Boost release detected."))
            sys.exit(0)
        self.stdout.write("No new Boost release.")
        sys.exit(1)
