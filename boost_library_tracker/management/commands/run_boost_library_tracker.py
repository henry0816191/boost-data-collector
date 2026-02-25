"""
Management command: run_boost_library_tracker

Runs several tasks in order:
  1. Fetch GitHub activity (main repo boostorg/boost + all submodules)
  2. Library tracker (stub; to be implemented)
  3. ...

For now only task 1 (fetch GitHub activity) is implemented.
"""

import logging
from datetime import datetime, timezone

import requests
from django.core.management.base import BaseCommand, CommandError

from cppa_user_tracker.services import get_or_create_owner_account
from github_activity_tracker.services import (
    ensure_repository_owner,
    get_or_create_repository,
)
from github_activity_tracker.sync import sync_github

from boost_library_tracker.services import get_or_create_boost_library_repo
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException

logger = logging.getLogger(__name__)

MAIN_OWNER = "boostorg"
MAIN_REPO = "boost"


def _parse_gitmodules_owner_repo(gitmodules_content: str) -> list[tuple[str, str]]:
    """Parse .gitmodules content and return list of (owner, repo) from each url."""
    result = []
    for line in gitmodules_content.split("\n"):
        line = line.strip()
        if not line.startswith("url ="):
            continue
        url = line.split("=", 1)[1].strip().replace(".git", "").rstrip("/")
        # e.g. https://github.com/boostorg/algorithm or ../algorithm
        if url.startswith("https://github.com/"):
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) >= 2:
                result.append((parts[0], parts[1]))
        elif url.startswith("../"):
            # relative: ../algorithm -> boostorg/algorithm
            result.append((MAIN_OWNER, url.replace("../", "")))
    return result


def task_fetch_github_activity(
    self,
    dry_run: bool = False,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    from_library: str | None = None,
) -> None:
    """Fetch GitHub activity for boostorg/boost and all its submodules.

    Args:
        dry_run: If True, only show what would be done.
        start_date: Start date for sync (default: auto from DB).
        end_date: End date for sync (default: now).
        from_library: If set, start at this repo (including main when 'boost') and sync it and all after.
            Use 'boost' for main repo or a submodule name (e.g. 'build', 'algorithm'). Default: sync all.
    """
    self.stdout.write("Task 1: Fetch GitHub activity (main repo + submodules)...")
    if start_date:
        self.stdout.write(f"  From: {start_date.isoformat()}")
    if end_date:
        self.stdout.write(f"  To: {end_date.isoformat()}")
    elif start_date:
        self.stdout.write("  To: now")
    if from_library:
        self.stdout.write(f"  From library: {from_library} (and all after)")

    client = get_github_client(use="scraping")

    # Resolve owner account for main repo (boostorg)
    try:
        owner_account = get_or_create_owner_account(client, MAIN_OWNER)
    except (ConnectionException, RateLimitException) as e:
        logger.exception("Failed to get owner account %s: %s", MAIN_OWNER, e)
        raise

    # Build list: main repo + submodules (owner, repo_name)
    repos_to_sync = [(MAIN_OWNER, MAIN_REPO)]

    try:
        content, _ = client.get_file_content(MAIN_OWNER, MAIN_REPO, ".gitmodules")
        if content:
            text = content.decode("utf-8")
            submodules = _parse_gitmodules_owner_repo(text)
            for owner, repo_name in submodules:
                if (owner, repo_name) not in repos_to_sync:
                    repos_to_sync.append((owner, repo_name))
            logger.debug(
                "Found %d submodules; total repos to sync: %d",
                len(submodules),
                len(repos_to_sync),
            )
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.debug(
                "No .gitmodules in %s/%s; syncing main repo only", MAIN_OWNER, MAIN_REPO
            )
        else:
            raise
    except Exception as e:
        logger.warning("Could not fetch .gitmodules: %s; syncing main repo only", e)

    # If --from-library is set, start at this repo (including main if NAME is 'boost') and all after
    if from_library:
        from_name = from_library.strip()
        idx = None
        for i, (_owner, repo_name) in enumerate(repos_to_sync):
            if repo_name == from_name:
                idx = i
                break
        if idx is None:
            logger.warning(
                "No submodule/repo with name '%s' found in repo list; starting from first (idx=0).",
                from_name,
            )
            idx = 0
        repos_to_sync = repos_to_sync[idx:]
        self.stdout.write(
            f"  Starting from {repos_to_sync[0][0]}/{repos_to_sync[0][1]} ({len(repos_to_sync)} repo(s))"
        )

    if dry_run:
        self.stdout.write(
            f"  Would sync {len(repos_to_sync)} repo(s): {repos_to_sync[:5]}{'...' if len(repos_to_sync) > 5 else ''}"
        )
        return

    owner_accounts = {MAIN_OWNER: owner_account}
    synced = 0
    for owner, repo_name in repos_to_sync:
        try:
            logger.debug("Syncing %s/%s", owner, repo_name)
            if owner not in owner_accounts:
                owner_accounts[owner] = get_or_create_owner_account(client, owner)
            acc = owner_accounts[owner]
            repo, _ = get_or_create_repository(acc, repo_name)
            ensure_repository_owner(repo, acc)
            boost_repo, _ = get_or_create_boost_library_repo(repo)
            sync_github(boost_repo, start_date=start_date, end_date=end_date)
            synced += 1
            self.stdout.write(self.style.SUCCESS(f"  Synced {owner}/{repo_name}"))
        except (ConnectionException, RateLimitException) as e:
            logger.exception("Sync failed for %s/%s: %s", owner, repo_name, e)
            raise
        except Exception as e:
            logger.exception("Sync failed for %s/%s: %s", owner, repo_name, e)
            raise

    self.stdout.write(
        self.style.SUCCESS(f"  GitHub activity: synced {synced} repo(s).")
    )


def task_library_tracker(self, dry_run: bool = False) -> None:
    """Library tracker (versions, dependencies, etc.). Stub for now."""
    self.stdout.write("Task 2: Library tracker (stub)...")
    if not dry_run:
        pass  # TODO: implement


class Command(BaseCommand):
    help = (
        "Run Boost Library Tracker: GitHub activity (boostorg/boost + submodules), then library tracker, etc. "
        "Currently only fetches GitHub activity."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show what would be done (e.g. repo list); do not sync.",
        )
        parser.add_argument(
            "--task",
            type=str,
            default=None,
            help="Run only this task: 'github_activity' or 'library_tracker'. Default: run all.",
        )
        parser.add_argument(
            "--from-date",
            type=str,
            default=None,
            help="Start date for sync (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: auto from DB.",
        )
        parser.add_argument(
            "--to-date",
            type=str,
            default=None,
            help="End date for sync (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: now.",
        )
        parser.add_argument(
            "--from-library",
            type=str,
            default=None,
            metavar="NAME",
            help="Start at this repo (including the main repo when NAME is 'boost') and sync it and all after. "
            "Use 'boost' for main repo or a submodule name (e.g. 'build', 'algorithm'). Default: sync all.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        task_filter = (options["task"] or "").strip().lower()

        # Parse date arguments
        start_date = None
        end_date = None
        if options.get("from_date"):
            try:
                start_date = datetime.fromisoformat(options["from_date"])
            except ValueError as e:
                self.stderr.write(
                    self.style.WARNING(f"Invalid --from-date format: {e}")
                )
                start_date = None
        if options.get("to_date"):
            try:
                end_date = datetime.fromisoformat(options["to_date"])
            except ValueError as e:
                self.stderr.write(self.style.WARNING(f"Invalid --to-date format: {e}"))
                end_date = None

        # Normalize to UTC-naive so comparison never mixes aware and naive
        if start_date and start_date.tzinfo:
            start_date = start_date.astimezone(timezone.utc).replace(tzinfo=None)
        if end_date and end_date.tzinfo:
            end_date = end_date.astimezone(timezone.utc).replace(tzinfo=None)

        if start_date and end_date and start_date > end_date:
            raise CommandError(
                f"Invalid date range: start_date ({start_date.isoformat()}) must be before "
                f"or equal to end_date ({end_date.isoformat()})."
            )

        from_library = (options.get("from_library") or "").strip() or None
        logger.debug(
            "run_boost_library_tracker: starting (dry_run=%s, task=%s, from=%s, to=%s, from_library=%s)",
            dry_run,
            task_filter or "all",
            start_date.isoformat() if start_date else "auto",
            end_date.isoformat() if end_date else "now",
            from_library or "all",
        )

        try:
            if not task_filter or task_filter == "github_activity":
                task_fetch_github_activity(
                    self,
                    dry_run=dry_run,
                    start_date=start_date,
                    end_date=end_date,
                    from_library=from_library,
                )
            if not task_filter or task_filter == "library_tracker":
                task_library_tracker(self, dry_run=dry_run)

            self.stdout.write(
                self.style.SUCCESS("run_boost_library_tracker: finished successfully")
            )
            logger.debug("run_boost_library_tracker: finished successfully")
        except Exception as e:
            logger.exception("run_boost_library_tracker failed: %s", e)
            raise
