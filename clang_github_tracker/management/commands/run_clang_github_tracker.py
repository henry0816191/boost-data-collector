"""
Management command: run_clang_github_tracker

Fetches GitHub activity for llvm/llvm-project and saves only to
raw/github_activity_tracker/llvm/llvm-project (no DB writes).

State (last commit/issue/PR dates) is stored in workspace/clang_github_activity/state.json.
If state is missing, it is created by scanning existing raw files or with nulls then scraping.
"""

import logging
from datetime import datetime, timezone

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from clang_github_tracker import state_manager as clang_state
from clang_github_tracker.sync_raw import sync_raw_only

logger = logging.getLogger(__name__)

PINECONE_NAMESPACE_ENV_KEY = "CLANG_GITHUB_PINECONE_NAMESPACE"


def _run_pinecone_sync(
    app_type: str, namespace: str, preprocessor_dotted_path: str
) -> None:
    """Trigger run_cppa_pinecone_sync if app_type and namespace are both set."""
    if not app_type:
        logger.warning("Pinecone sync skipped: --pinecone-app-type is empty.")
        return
    if not namespace:
        logger.warning(
            "Pinecone sync skipped: namespace is empty (set --pinecone-namespace or %s).",
            PINECONE_NAMESPACE_ENV_KEY,
        )
        return
    try:
        call_command(
            "run_cppa_pinecone_sync",
            app_type=app_type,
            namespace=namespace,
            preprocessor=preprocessor_dotted_path,
        )
        logger.info(
            "run_clang_github_tracker: pinecone sync completed (app_type=%s, namespace=%s)",
            app_type,
            namespace,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Pinecone sync skipped/failed (run_cppa_pinecone_sync unavailable or errored): %s",
            exc,
        )


class Command(BaseCommand):
    """Django management command: fetch GitHub activity to raw and optionally run sync."""

    help = (
        "Run Clang GitHub Tracker: fetch llvm/llvm-project activity to "
        "raw/github_activity_tracker only (no DB). Uses workspace/clang_github_activity/state.json for resume."
    )

    def add_arguments(self, parser):
        """Register --dry-run, --from-date, --to-date, --pinecone-app-type, --pinecone-namespace."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show resolved start/end dates and state; do not fetch.",
        )
        parser.add_argument(
            "--from-date",
            type=str,
            default=None,
            help="Start date for sync (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). Default: from state or raw scan.",
        )
        parser.add_argument(
            "--to-date",
            type=str,
            default=None,
            help="End date for sync (ISO format). Default: now.",
        )
        parser.add_argument(
            "--pinecone-app-type",
            type=str,
            default=settings.CLANG_GITHUB_PINECONE_APP_TYPE,
            help="App type passed to run_cppa_pinecone_sync. Default from env CLANG_GITHUB_PINECONE_APP_TYPE.",
        )
        parser.add_argument(
            "--pinecone-namespace",
            type=str,
            default=settings.CLANG_GITHUB_PINECONE_NAMESPACE,
            help=f"Pinecone namespace for sync. Default from env {PINECONE_NAMESPACE_ENV_KEY}.",
        )

    def handle(self, *args, **options):
        """Resolve dates from state or CLI, then run sync unless --dry-run."""
        dry_run = options["dry_run"]
        from_date_str = (options.get("from_date") or "").strip()
        to_date_str = (options.get("to_date") or "").strip()
        pinecone_app_type = (
            options.get("pinecone_app_type") or ""
        ).strip() or settings.CLANG_GITHUB_PINECONE_APP_TYPE
        pinecone_namespace = (
            options.get("pinecone_namespace") or ""
        ).strip() or settings.CLANG_GITHUB_PINECONE_NAMESPACE

        from_date = None
        to_date = None
        if from_date_str:
            try:
                from_date = datetime.fromisoformat(from_date_str)
            except ValueError as e:
                logger.warning("Invalid --from-date: %s", e)
        if to_date_str:
            try:
                to_date = datetime.fromisoformat(to_date_str)
            except ValueError as e:
                logger.warning("Invalid --to-date: %s", e)

        # Normalize to UTC for comparison
        if from_date and from_date.tzinfo is None:
            from_date = from_date.replace(tzinfo=timezone.utc)
        elif from_date:
            from_date = from_date.astimezone(timezone.utc)
        if to_date and to_date.tzinfo is None:
            to_date = to_date.replace(tzinfo=timezone.utc)
        elif to_date:
            to_date = to_date.astimezone(timezone.utc)

        if from_date and to_date and from_date > to_date:
            raise CommandError(
                "Invalid date range: from_date must be before or equal to to_date."
            )

        resolved = clang_state.resolve_start_end_dates(from_date, to_date)
        if resolved is None:
            return

        start_commit, start_issue, start_pr, end_date = resolved
        logger.info(
            "Resolved: start_commit=%r start_issue=%r start_pr=%r end=%r",
            start_commit,
            start_issue,
            start_pr,
            end_date,
        )
        if dry_run:
            logger.info("Dry run: no fetch performed.")
            return

        try:
            commits_saved, issues_saved, prs_saved = sync_raw_only(
                start_commit=start_commit,
                start_issue=start_issue,
                start_pr=start_pr,
                end_date=end_date,
            )
            logger.info(
                "run_clang_github_tracker: saved commits=%s issues=%s prs=%s",
                commits_saved,
                issues_saved,
                prs_saved,
            )
        except Exception as e:
            logger.exception("run_clang_github_tracker failed: %s", e)
            raise

        # Phase: upsert issues and PRs to Pinecone
        effective_app_type = (
            pinecone_app_type or settings.CLANG_GITHUB_PINECONE_APP_TYPE
        )
        effective_namespace = (
            pinecone_namespace or settings.CLANG_GITHUB_PINECONE_NAMESPACE
        )
        _run_pinecone_sync(
            effective_app_type,
            effective_namespace,
            "clang_github_tracker.preprocessors.issue_preprocessor.preprocess_for_pinecone",
        )
        _run_pinecone_sync(
            effective_app_type,
            effective_namespace,
            "clang_github_tracker.preprocessors.pr_preprocessor.preprocess_for_pinecone",
        )
