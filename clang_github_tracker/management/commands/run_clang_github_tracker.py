"""
Management command: run_clang_github_tracker

Fetches GitHub activity for llvm/llvm-project, saves raw JSON and DB rows, optionally
exports Markdown and pushes to the configured Clang markdown GitHub repo. Resume uses DB watermarks (not state.json).
"""

import logging
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core.utils.datetime_parsing import parse_iso_datetime
from clang_github_tracker import state_manager as clang_state
from clang_github_tracker.sync_raw import sync_clang_github_activity
from clang_github_tracker.publisher import publish_clang_markdown
from clang_github_tracker.workspace import OWNER, REPO, get_workspace_root

from operations.md_ops.github_export import write_md_files

logger = logging.getLogger(__name__)

DEFAULT_CLANG_REPO_BRANCH = "master"


def _run_pinecone_sync(
    app_type: str, namespace: str, preprocessor_dotted_path: str
) -> None:
    """Trigger run_cppa_pinecone_sync if app_type and namespace are both set."""
    if not app_type:
        logger.warning(
            "Pinecone sync skipped: CLANG_GITHUB_PINECONE_APP_TYPE is empty (settings/env)."
        )
        return
    if not namespace:
        logger.warning(
            "Pinecone sync skipped: CLANG_GITHUB_PINECONE_NAMESPACE is empty (settings/env)."
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
    """Django management command: fetch GitHub activity to raw + DB; optional MD, push, Pinecone."""

    help = (
        "Run Clang GitHub Tracker: fetch llvm/llvm-project activity to "
        "raw/github_activity_tracker and DB. Uses DB cursor for resume (not state.json). "
        "Use --skip-* to skip steps; default runs all."
    )

    def add_arguments(self, parser):
        """Define dry-run, skip flags, and optional ``--since`` / ``--until`` window."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No sync, export, push, or Pinecone writes; resolved windows logged at INFO.",
        )
        parser.add_argument(
            "--skip-github-sync",
            action="store_true",
            help="Skip API fetch / sync_clang_github_activity (raw JSON + DB upserts).",
        )
        parser.add_argument(
            "--skip-markdown-export",
            action="store_true",
            help="Skip writing .md files from this run's sync results.",
        )
        parser.add_argument(
            "--skip-remote-push",
            action="store_true",
            help="Skip push to the repo configured via CLANG_GITHUB_CONTEXT_REPO_OWNER / CLANG_GITHUB_CONTEXT_REPO_NAME.",
        )
        parser.add_argument(
            "--skip-pinecone",
            action="store_true",
            help="Skip run_cppa_pinecone_sync for issues and PRs.",
        )
        parser.add_argument(
            "--since",
            "--from-date",
            "--start-time",
            type=str,
            default=None,
            dest="since",
            help="Sync window start: YYYY-MM-DD or ISO-8601. "
            "--from-date / --start-time are aliases for --since.",
        )
        parser.add_argument(
            "--until",
            "--to-date",
            "--end-time",
            type=str,
            default=None,
            dest="until",
            help="Sync window end: same formats as --since. "
            "--to-date / --end-time are aliases for --until.",
        )

    def handle(self, *args, **options):
        """Resolve sync window, then run GitHub fetch, Markdown, push, and Pinecone as configured."""
        dry_run = options["dry_run"]
        skip_github_sync = options["skip_github_sync"]
        skip_markdown_export = options["skip_markdown_export"]
        skip_remote_push = options["skip_remote_push"]
        skip_pinecone = options["skip_pinecone"]

        try:
            since = parse_iso_datetime(options.get("since"))
            until = parse_iso_datetime(options.get("until"))
        except ValueError as e:
            raise CommandError(str(e)) from e

        start_commit, start_item, end_date = clang_state.resolve_start_end_dates(
            since, until
        )
        logger.info(
            "Resolved: start_commit=%r start_item=%r end=%r",
            start_commit,
            start_item,
            end_date,
        )

        # Dry run

        if dry_run:
            if not skip_github_sync:
                logger.info("dry-run: would run GitHub sync for llvm/llvm-project")
            else:
                logger.info("dry-run: skipping GitHub sync (--skip-github-sync)")
            if not skip_markdown_export:
                logger.info("dry-run: would export Markdown for issues/PRs from sync")
            if not skip_remote_push:
                logger.info("dry-run: would push Markdown to configured Clang repo")
            if not skip_pinecone:
                logger.info("dry-run: would run Pinecone upsert for issues and PRs")
            logger.info("dry-run finished")
            return

        issue_numbers: list[int] = []
        pr_numbers: list[int] = []

        # GitHub sync

        if not skip_github_sync:
            try:
                commits_saved, issue_numbers, pr_numbers = sync_clang_github_activity(
                    start_commit=start_commit,
                    start_item=start_item,
                    end_date=end_date,
                )
                logger.info(
                    "run_clang_github_tracker: sync done; commits=%s issues=%s prs=%s",
                    commits_saved,
                    len(issue_numbers),
                    len(pr_numbers),
                )
            except Exception as e:
                logger.exception("run_clang_github_tracker sync failed: %s", e)
                raise
        else:
            logger.info("skipping GitHub sync (--skip-github-sync)")

        # Markdown export

        md_output_dir = get_workspace_root() / "md_export"
        md_output_dir.mkdir(parents=True, exist_ok=True)

        new_files: dict[str, str] = {}
        if not skip_markdown_export:
            if issue_numbers or pr_numbers:
                logger.info("writing MD to %s", md_output_dir)
                new_files = write_md_files(
                    owner=OWNER,
                    repo=REPO,
                    issue_numbers=issue_numbers,
                    pr_numbers=pr_numbers,
                    output_dir=md_output_dir,
                    folder_prefix="",
                )
                logger.info(
                    "run_clang_github_tracker: generated %s MD file(s).",
                    len(new_files),
                )
            elif skip_github_sync:
                logger.info("skipped Markdown export (no sync in this run)")
            else:
                logger.info(
                    "run_clang_github_tracker: no issues/PRs synced; skipping MD export."
                )
        else:
            logger.info("skipping Markdown export (--skip-markdown-export)")

        # Remote push

        if not skip_remote_push:
            logger.info("push Markdown to configured GitHub repo")
            self._push_markdown(md_output_dir, new_files)
        else:
            logger.info("skipping remote push (--skip-remote-push)")

        # Pinecone sync

        if not skip_pinecone:
            app_type = (settings.CLANG_GITHUB_PINECONE_APP_TYPE or "").strip()
            namespace = (settings.CLANG_GITHUB_PINECONE_NAMESPACE or "").strip()
            if not app_type:
                logger.warning(
                    "Pinecone sync skipped: CLANG_GITHUB_PINECONE_APP_TYPE is empty (settings/env)."
                )
            else:
                _run_pinecone_sync(
                    f"{app_type}-issues",
                    namespace,
                    "clang_github_tracker.preprocessors.issue_preprocessor.preprocess_for_pinecone",
                )
                _run_pinecone_sync(
                    f"{app_type}-prs",
                    namespace,
                    "clang_github_tracker.preprocessors.pr_preprocessor.preprocess_for_pinecone",
                )
        else:
            logger.info("skipping Pinecone (--skip-pinecone)")

        logger.info("run_clang_github_tracker finished successfully")

    def _push_markdown(self, md_output_dir: Path, new_files: dict[str, str]) -> None:
        """Publish ``md_export`` to ``CLANG_GITHUB_CONTEXT_*`` and remove local run artifacts."""
        clang_github_context_repo_owner = getattr(
            settings, "CLANG_GITHUB_CONTEXT_REPO_OWNER", ""
        ).strip()
        clang_github_context_repo_name = getattr(
            settings, "CLANG_GITHUB_CONTEXT_REPO_NAME", ""
        ).strip()
        clang_github_context_repo_branch = (
            getattr(settings, "CLANG_GITHUB_CONTEXT_REPO_BRANCH", "") or ""
        ).strip() or DEFAULT_CLANG_REPO_BRANCH
        if not clang_github_context_repo_owner or not clang_github_context_repo_name:
            logger.error(
                "CLANG_GITHUB_CONTEXT_REPO_OWNER / CLANG_GITHUB_CONTEXT_REPO_NAME "
                "not configured; skipping Markdown push."
            )
            return

        publish_clang_markdown(
            md_output_dir,
            clang_github_context_repo_owner,
            clang_github_context_repo_name,
            clang_github_context_repo_branch,
            new_files,
        )
        logger.info("run_clang_github_tracker: MD publish complete.")
        for local_path in new_files.values():
            Path(local_path).unlink(missing_ok=True)
