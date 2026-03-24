"""
Management command: run_clang_github_tracker

Fetches GitHub activity for llvm/llvm-project and saves only to
raw/github_activity_tracker/llvm/llvm-project (no DB writes).

State (last commit/issue/PR dates) is stored in workspace/clang_github_activity/state.json.
If state is missing, it is created by scanning existing raw files or with nulls then scraping.

After sync, updated issues/PRs are exported as Markdown and pushed to the private repo
configured via CLANG_GITHUB_TRACKER_PRIVATE_REPO_* settings.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from clang_github_tracker import state_manager as clang_state
from clang_github_tracker.sync_raw import sync_raw_only
from clang_github_tracker.workspace import OWNER, REPO, get_workspace_root
from github_ops import get_github_token, upload_folder_to_github
from operations.md_ops.github_export import (
    detect_renames_from_dirs,
    write_md_files,
)

logger = logging.getLogger(__name__)

DEFAULT_PRIVATE_MD_BRANCH = "master"
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
        """Register --dry-run, --from-date, --to-date, --no-upload, --pinecone-app-type, --pinecone-namespace."""
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
            "--no-upload",
            action="store_true",
            help="Generate Markdown files but skip pushing to GitHub (useful for inspection).",
        )
        parser.add_argument(
            "--upload-only",
            action="store_true",
            help="Only upload existing MD files from workspace (no sync, no MD generation).",
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
        """Resolve dates from state or CLI, then run sync unless --dry-run or --upload-only."""
        dry_run = options["dry_run"]
        no_upload = options.get("no_upload", False)
        upload_only = options.get("upload_only", False)
        from_date_str = (options.get("from_date") or "").strip()
        to_date_str = (options.get("to_date") or "").strip()
        pinecone_app_type = (
            options.get("pinecone_app_type") or ""
        ).strip() or settings.CLANG_GITHUB_PINECONE_APP_TYPE
        pinecone_namespace = (
            options.get("pinecone_namespace") or ""
        ).strip() or settings.CLANG_GITHUB_PINECONE_NAMESPACE

        if upload_only:
            self._upload_md_only(dry_run=dry_run)
            return

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
            commits_saved, issue_numbers, pr_numbers = sync_raw_only(
                start_commit=start_commit,
                start_issue=start_issue,
                start_pr=start_pr,
                end_date=end_date,
            )
            logger.info(
                "run_clang_github_tracker: saved commits=%s issues=%s prs=%s",
                commits_saved,
                len(issue_numbers),
                len(pr_numbers),
            )
        except Exception as e:
            logger.exception("run_clang_github_tracker failed: %s", e)
            raise

        if not issue_numbers and not pr_numbers:
            logger.info(
                "run_clang_github_tracker: no issues/PRs synced; skipping MD export."
            )
            return

        md_output_dir = get_workspace_root() / "md_export"
        md_output_dir.mkdir(parents=True, exist_ok=True)
        self.stdout.write(f"Writing MD to {md_output_dir}")

        try:
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

            if not new_files:
                logger.info(
                    "run_clang_github_tracker: no MD files generated; skipping upload."
                )
                return

            if no_upload:
                logger.info(
                    "run_clang_github_tracker: --no-upload set; skipping GitHub push."
                )
                return

            private_owner = getattr(
                settings, "CLANG_GITHUB_TRACKER_PRIVATE_REPO_OWNER", ""
            ).strip()
            private_repo_name = getattr(
                settings, "CLANG_GITHUB_TRACKER_PRIVATE_REPO_NAME", ""
            ).strip()
            private_branch = (
                getattr(
                    settings,
                    "CLANG_GITHUB_TRACKER_PRIVATE_REPO_BRANCH",
                    DEFAULT_PRIVATE_MD_BRANCH,
                )
                or DEFAULT_PRIVATE_MD_BRANCH
            ).strip()
            if not private_owner or not private_repo_name:
                logger.error(
                    "CLANG_GITHUB_TRACKER_PRIVATE_REPO_OWNER / CLANG_GITHUB_TRACKER_PRIVATE_REPO_NAME "
                    "not configured; skipping upload."
                )
                return

            token = get_github_token(use="write")
            delete_paths = detect_renames_from_dirs(
                private_owner,
                private_repo_name,
                private_branch,
                new_files,
                token=token,
            )
            for repo_rel in delete_paths:
                stale_local = md_output_dir / repo_rel
                if stale_local.exists():
                    stale_local.unlink()
            if delete_paths:
                logger.info(
                    "run_clang_github_tracker: %s renamed file(s) to delete.",
                    len(delete_paths),
                )

            result = upload_folder_to_github(
                local_folder=md_output_dir,
                owner=private_owner,
                repo=private_repo_name,
                commit_message="chore: update Clang issues/PRs markdown",
                branch=private_branch,
                delete_paths=delete_paths or None,
            )

            if result.get("success"):
                logger.info("run_clang_github_tracker: MD upload complete.")
                for local_path in new_files.values():
                    Path(local_path).unlink(missing_ok=True)
            else:
                msg = result.get("message") or "Upload failed"
                logger.error("run_clang_github_tracker: MD upload failed: %s", msg)
                raise CommandError(msg)
        except Exception as e:
            logger.exception("run_clang_github_tracker: MD export/upload failed: %s", e)
            raise

        # Phase: upsert issues and PRs to Pinecone
        effective_app_type = (
            pinecone_app_type or settings.CLANG_GITHUB_PINECONE_APP_TYPE
        )
        effective_namespace = (
            pinecone_namespace or settings.CLANG_GITHUB_PINECONE_NAMESPACE
        )
        _run_pinecone_sync(
            f"{effective_app_type}-issues",
            effective_namespace,
            "clang_github_tracker.preprocessors.issue_preprocessor.preprocess_for_pinecone",
        )
        _run_pinecone_sync(
            f"{effective_app_type}-prs",
            effective_namespace,
            "clang_github_tracker.preprocessors.pr_preprocessor.preprocess_for_pinecone",
        )

    def _upload_md_only(self, *, dry_run: bool = False):
        """Upload existing MD files from workspace/clang_github_activity/md_export (no sync, no generation)."""
        if dry_run:
            logger.info(
                "run_clang_github_tracker: --upload-only with --dry-run; skipping upload."
            )
            return
        md_output_dir = get_workspace_root() / "md_export"
        if not md_output_dir.is_dir():
            self.stdout.write(
                self.style.WARNING(
                    f"No md_export folder at {md_output_dir}; nothing to upload."
                )
            )
            return

        new_files = {}
        for root, _dirs, files in os.walk(md_output_dir):
            for name in files:
                if not name.endswith(".md"):
                    continue
                path = Path(root) / name
                repo_rel = path.relative_to(md_output_dir).as_posix()
                new_files[repo_rel] = str(path)

        if not new_files:
            self.stdout.write(
                self.style.WARNING("No .md files in md_export; nothing to upload.")
            )
            return

        self.stdout.write(f"Writing MD to {md_output_dir}")
        self.stdout.write(f"Found {len(new_files)} .md file(s) to upload.")

        private_owner = getattr(
            settings, "CLANG_GITHUB_TRACKER_PRIVATE_REPO_OWNER", ""
        ).strip()
        private_repo_name = getattr(
            settings, "CLANG_GITHUB_TRACKER_PRIVATE_REPO_NAME", ""
        ).strip()
        private_branch = (
            getattr(
                settings,
                "CLANG_GITHUB_TRACKER_PRIVATE_REPO_BRANCH",
                DEFAULT_PRIVATE_MD_BRANCH,
            )
            or DEFAULT_PRIVATE_MD_BRANCH
        ).strip()

        if not private_owner or not private_repo_name:
            logger.error(
                "CLANG_GITHUB_TRACKER_PRIVATE_REPO_OWNER / CLANG_GITHUB_TRACKER_PRIVATE_REPO_NAME "
                "not configured."
            )
            self.stdout.write(
                self.style.ERROR(
                    "Private repo not configured; set CLANG_GITHUB_TRACKER_PRIVATE_REPO_*."
                )
            )
            return

        try:
            token = get_github_token(use="write")
            delete_paths = detect_renames_from_dirs(
                private_owner,
                private_repo_name,
                private_branch,
                new_files,
                token=token,
            )
            for repo_rel in delete_paths:
                stale_local = md_output_dir / repo_rel
                if stale_local.exists():
                    stale_local.unlink()
            if delete_paths:
                logger.info(
                    "run_clang_github_tracker: %s renamed file(s) to delete.",
                    len(delete_paths),
                )

            result = upload_folder_to_github(
                local_folder=md_output_dir,
                owner=private_owner,
                repo=private_repo_name,
                commit_message="chore: update Clang issues/PRs markdown",
                branch=private_branch,
                delete_paths=delete_paths or None,
            )

            if result.get("success"):
                self.stdout.write(self.style.SUCCESS("MD upload complete."))
                logger.info("run_clang_github_tracker: MD upload complete.")
                for local_path in new_files.values():
                    Path(local_path).unlink(missing_ok=True)
            else:
                msg = result.get("message") or "Upload failed"
                self.stdout.write(self.style.ERROR(f"Upload failed: {msg}"))
                logger.error(
                    "run_clang_github_tracker: MD upload failed: %s",
                    msg,
                )
                raise CommandError(msg)
        except Exception as e:
            logger.exception("run_clang_github_tracker: upload-only failed: %s", e)
            raise
