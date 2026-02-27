"""
Management command: run_boost_usage_tracker

Two processing units:

1. **monitor_content** (daily):
   Find all repos pushed in a date range with 10+ stars in C++ language.
   For each repo, search for ``#include <boost/…>``, resolve headers to
   BoostFile, and update BoostExternalRepository / BoostUsage tables.

2. **monitor_stars** (monthly):
   Find all C++ repos with 10+ stars created since 2008-04-01.
   For repos *not already tracked* in BoostExternalRepository, check Boost
   usage and update tables.
"""

import logging
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand
from django.utils import timezone as django_tz
from django.utils.dateparse import parse_datetime

from boost_usage_tracker.models import BoostExternalRepository
from github_activity_tracker.models import GitHubRepository
from boost_usage_tracker.boost_searcher import (
    BOOST_INCLUDE_SEARCH_BATCH_SIZE,
    search_boost_include_files_batch,
)
from boost_usage_tracker.post_process import process_single_repo
from boost_usage_tracker.repo_searcher import (
    RepoSearchResult,
    search_repos_with_date_splitting,
    CREATION_START_DEFAULT,
)
from cppa_user_tracker.services import get_or_create_owner_account
from github_activity_tracker.services import (
    get_or_create_repository,
)
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure GitHubRepository from a search result
# ---------------------------------------------------------------------------


def _ensure_github_repo(client, result: RepoSearchResult):
    """Ensure a GitHubRepository (and owner account) exist for *result*.

    Returns the :class:`GitHubRepository` instance.
    """
    owner_name, repo_name = result.full_name.split("/", 1)
    owner_account = get_or_create_owner_account(client, owner_name)

    defaults = {
        "stars": result.stars,
        "description": result.description,
        "forks": result.forks,
    }
    if result.pushed_at:
        defaults["repo_pushed_at"] = parse_datetime(result.pushed_at)
    if result.created_at:
        defaults["repo_created_at"] = parse_datetime(result.created_at)
    if result.updated_at:
        defaults["repo_updated_at"] = parse_datetime(result.updated_at)

    repo, _ = get_or_create_repository(owner_account, repo_name, **defaults)
    return repo


def _run_boost_search_stage(
    client,
    repo_results: list[RepoSearchResult],
    last_commit_dt: datetime,
    log_label: str = "",
) -> dict:
    """Shared boost-search stage used by both tasks.

    Steps:
    1) Batch code-search includes for up to 5 repos.
    2) Group file matches by repo.
    3) Run per-repo persistence pipeline.
    """
    totals = {
        "processed": 0,
        "boost_used": 0,
        "usages_created": 0,
        "usages_updated": 0,
        "usages_excepted": 0,
    }

    batch_size = BOOST_INCLUDE_SEARCH_BATCH_SIZE
    for batch_start in range(0, len(repo_results), batch_size):
        batch = repo_results[batch_start : batch_start + batch_size]
        batch_names = [r.full_name for r in batch]
        logger.info(
            "(%d-%d/%d) [%s] Batch code search for %s",
            batch_start + 1,
            batch_start + len(batch),
            len(repo_results),
            log_label or "boost_search",
            batch_names,
        )
        try:
            batch_file_results = search_boost_include_files_batch(client, batch_names)
        except (ConnectionException, RateLimitException) as e:
            logger.exception("Rate limit / connection error during batch search: %s", e)
            raise

        files_in_batch = len(batch_file_results)
        logger.info(
            "  [%s] Batch found %d file(s) with Boost includes",
            log_label or "boost_search",
            files_in_batch,
        )

        by_repo: dict[str, list] = {}
        for fr in batch_file_results:
            by_repo.setdefault(fr.repo_full_name, []).append(fr)

        batch_usages_created = 0
        batch_usages_updated = 0
        batch_usages_excepted = 0
        batch_missing_headers = 0

        for repo_result in batch:
            file_results_for_repo = by_repo.get(repo_result.full_name, [])
            logger.info(
                "  [%s] Processing %s",
                log_label or "boost_search",
                repo_result.full_name,
            )
            try:
                stats = process_single_repo(
                    client,
                    repo_result,
                    file_results_for_repo=file_results_for_repo,
                    db_last_commit_date=last_commit_dt,
                    ensure_repo_fn=_ensure_github_repo,
                )
                totals["processed"] += 1
                totals["boost_used"] += int(stats["boost_used"])
                totals["usages_created"] += stats["usages_created"]
                totals["usages_updated"] += stats["usages_updated"]
                totals["usages_excepted"] += stats["usages_excepted"]
                batch_usages_created += stats["usages_created"]
                batch_usages_updated += stats["usages_updated"]
                batch_usages_excepted += stats["usages_excepted"]
                batch_missing_headers += stats.get("missing_header_recorded", 0)
            except (ConnectionException, RateLimitException) as e:
                logger.exception(
                    "Rate limit / connection error at %s: %s",
                    repo_result.full_name,
                    e,
                )
                raise
            except Exception as e:
                logger.warning("Skipping %s due to error: %s", repo_result.full_name, e)

        batch_usages_total = batch_usages_created + batch_usages_updated
        logger.info(
            "  [%s] Batch summary: %d files → %d header usages (created=%d, updated=%d), excepted=%d, missing_header_recorded=%d",
            log_label or "boost_search",
            files_in_batch,
            batch_usages_total,
            batch_usages_created,
            batch_usages_updated,
            batch_usages_excepted,
            batch_missing_headers,
        )

    return totals


# ---------------------------------------------------------------------------
# Task 1: monitor_content (daily)
# ---------------------------------------------------------------------------


def task_monitor_content(
    since: datetime,
    until: datetime,
    min_stars: int,
    dry_run: bool,
) -> None:
    """Daily task: find repos pushed in *[since, until]* and check Boost usage."""
    logger.info(
        "Task: monitor_content (daily) — pushed:%s..%s, stars>%s",
        since.date(),
        until.date(),
        min_stars,
    )
    client = get_github_client(use="scraping")

    repo_results = search_repos_with_date_splitting(
        client,
        since,
        until,
        date_field="pushed",
        min_stars=min_stars,
    )

    logger.info("Found %d repos pushed in date range", len(repo_results))

    if dry_run:
        for r in repo_results[:20]:
            logger.info("  %s (%s stars)", r.full_name, r.stars)
        if len(repo_results) > 20:
            logger.info("  … and %d more", len(repo_results) - 20)
        return

    totals = _run_boost_search_stage(
        client,
        repo_results,
        last_commit_dt=since,
        log_label="monitor_content",
    )

    logger.info("monitor_content complete: %s", totals)


# ---------------------------------------------------------------------------
# Task 2: monitor_stars (monthly)
# ---------------------------------------------------------------------------


def task_monitor_stars(
    min_stars: int,
    dry_run: bool,
) -> None:
    """Monthly task: find all C++ repos with 10+ stars, process new ones."""
    now = datetime.now(timezone.utc)
    client = get_github_client(use="scraping")

    # Load all already-tracked repos with their current star counts.
    # full_name is "owner/repo_name"; map to (repo_pk, current_stars) so we can
    # detect star changes without a second DB round-trip.
    tracked_repos: dict[str, tuple[int, int]] = {
        f"{owner}/{repo}": (pk, stars)
        for pk, owner, repo, stars in BoostExternalRepository.objects.values_list(
            "githubrepository_ptr_id",
            "owner_account__username",
            "repo_name",
            "stars",
        )
    }

    start_date = CREATION_START_DEFAULT
    if dry_run:
        start_date = now - timedelta(days=30)

    new_repos: list[RepoSearchResult] = []
    stars_to_update: dict[int, int] = (
        {}
    )  # {repo_pk: new_stars} for tracked repos whose stars changed

    results = search_repos_with_date_splitting(
        client,
        start_date,
        now,
        date_field="created",
        min_stars=min_stars,
    )
    for r in results:
        if r.full_name not in tracked_repos:
            new_repos.append(r)
            # Mark as seen so cross-range duplicates are not double-processed.
            tracked_repos[r.full_name] = (-1, r.stars)
        else:
            repo_pk, current_stars = tracked_repos[r.full_name]
            if repo_pk != -1 and r.stars != current_stars:
                stars_to_update[repo_pk] = r.stars
                # Update local cache to avoid overwriting with an older range value.
                tracked_repos[r.full_name] = (repo_pk, r.stars)

    logger.info(
        "Found %d new repos not yet tracked; %d tracked repos have updated star counts",
        len(new_repos),
        len(stars_to_update),
    )

    # Bulk-update star counts for already-tracked repos where the count changed.
    if stars_to_update and not dry_run:
        repos_to_refresh = list(
            GitHubRepository.objects.filter(pk__in=stars_to_update.keys())
        )
        now = django_tz.now()
        for repo_obj in repos_to_refresh:
            repo_obj.stars = stars_to_update[repo_obj.pk]
            repo_obj.updated_at = now
        GitHubRepository.objects.bulk_update(repos_to_refresh, ["stars", "updated_at"])
        logger.info("Bulk-updated stars for %d repos", len(repos_to_refresh))

    if dry_run:
        for r in new_repos[:20]:
            logger.info("  new: %s (%s stars)", r.full_name, r.stars)
        if len(new_repos) > 20:
            logger.info("  … and %d more new", len(new_repos) - 20)
        for pk, new_stars in list(stars_to_update.items())[:20]:
            logger.info("  stars changed: repo_pk=%d → %d stars", pk, new_stars)
        return

    totals = _run_boost_search_stage(
        client,
        new_repos,
        last_commit_dt=CREATION_START_DEFAULT,
        log_label="monitor_stars",
    )

    logger.info("monitor_stars complete: %s", totals)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Run Boost Usage Tracker: detect Boost library usage in external C++ "
        "repositories.\n\n"
        "Two tasks:\n"
        "  monitor_content (daily): repos pushed in date range.\n"
        "  monitor_stars  (monthly): all C++ repos with 10+ stars."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--task",
            type=str,
            default=None,
            choices=["monitor_content", "monitor_stars"],
            help=(
                "Run only this task. Default: run both in order "
                "(monitor_content then monitor_stars)."
            ),
        )
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Start date for monitor_content (YYYY-MM-DD). Default: yesterday.",
        )
        parser.add_argument(
            "--until",
            type=str,
            default=None,
            help="End date for monitor_content (YYYY-MM-DD). Default: today.",
        )
        parser.add_argument(
            "--min-stars",
            type=int,
            default=10,
            help="Minimum stars filter (default: 10).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show what would be done; do not modify the database.",
        )

    def handle(self, *args, **options):
        task_filter = (options["task"] or "").strip().lower()
        dry_run = options["dry_run"]
        min_stars = options["min_stars"]

        now = datetime.now(timezone.utc)

        def _parse_ymd_or_none(value, opt_name):
            if not value:
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(
                    "Invalid %s '%s'; falling back to default.", opt_name, value
                )
                return None

        until = _parse_ymd_or_none(options["until"], "--until") or now
        since = _parse_ymd_or_none(options["since"], "--since") or (
            until - timedelta(days=1)
        )

        logger.info(
            "run_boost_usage_tracker: starting (task=%s, dry_run=%s)",
            task_filter or "all",
            dry_run,
        )

        try:
            if not task_filter or task_filter == "monitor_content":
                task_monitor_content(since, until, min_stars, dry_run)

            if not task_filter or task_filter == "monitor_stars":
                task_monitor_stars(min_stars, dry_run)

            logger.info("run_boost_usage_tracker: finished successfully")
        except (ConnectionException, RateLimitException) as e:
            logger.exception(
                "run_boost_usage_tracker failed (rate limit / connection): %s",
                e,
            )
            raise
        except Exception as e:
            logger.exception("run_boost_usage_tracker failed: %s", e)
            raise
