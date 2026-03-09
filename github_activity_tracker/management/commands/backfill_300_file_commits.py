"""
Backfill commits that have exactly 300 file changes (API truncation).

Finds commits in the database with 300 file_changes, fetches the full
file list via git (using get_full_commit_files), and updates the database.

Run: python manage.py backfill_300_file_commits [--dry-run] [--limit N]
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from github_activity_tracker import big_commit
from github_activity_tracker.models import GitCommit, GitCommitFileChange
from github_activity_tracker.sync.commits import _process_commit_files
from github_activity_tracker.workspace import (
    clear_clone_registry,
    get_registered_clones,
    remove_clone_dir,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Find commits with exactly 300 file changes (truncated by API), "
        "fetch full file list via git, and update the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only list commits that would be updated; do not change the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            metavar="N",
            help="Process at most N commits (0 = no limit).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]

        # Find commits with exactly 300 file changes
        commits_300 = (
            GitCommit.objects.annotate(file_count=Count("file_changes"))
            .filter(file_count=300)
            .select_related("repo", "repo__owner_account")
            .order_by("id")
        )
        if limit > 0:
            commits_300 = list(commits_300[:limit])
        total = len(commits_300) if limit > 0 else commits_300.count()
        if total == 0:
            self.stdout.write(
                self.style.SUCCESS("No commits with exactly 300 file changes found.")
            )
            return

        self.stdout.write(
            f"Found {total} commit(s) with 300 file changes (possibly truncated)."
        )
        if dry_run:
            for c in commits_300:
                owner = c.repo.owner_account.username
                self.stdout.write(
                    f"  Would backfill: {owner}/{c.repo.repo_name} {c.commit_hash[:7]}"
                )
            self.stdout.write(self.style.WARNING("Dry run: no changes made."))
            return

        updated = 0
        failed = 0

        try:
            for commit_obj in commits_300:
                repo = commit_obj.repo
                owner = repo.owner_account.username
                repo_name = repo.repo_name
                sha = commit_obj.commit_hash

                self.stdout.write(f"Backfilling {owner}/{repo_name} {sha[:7]}...")

                try:
                    # Get full file list via clone + git diff (parents resolved via git log if needed)
                    full_files = big_commit.get_full_commit_files(
                        owner, repo_name, commit_sha=sha
                    )

                    # Replace file changes in DB: delete existing, re-add with full list
                    with transaction.atomic():
                        GitCommitFileChange.objects.filter(commit=commit_obj).delete()
                        _process_commit_files(repo, commit_obj, full_files)

                    new_count = commit_obj.file_changes.count()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Updated: 300 -> {new_count} file changes"
                        )
                    )
                    updated += 1

                except Exception as e:
                    logger.exception(
                        "Failed to backfill %s/%s %s: %s",
                        owner,
                        repo_name,
                        sha[:7],
                        e,
                    )
                    self.stdout.write(self.style.ERROR(f"  Failed: {e}"))
                    failed += 1

            self.stdout.write(
                self.style.SUCCESS(f"Done. Updated {updated}, failed {failed}.")
            )

        finally:
            # Clean up cloned repos created during run
            clones = get_registered_clones()
            if clones:
                self.stdout.write(f"Cleaning up {len(clones)} cloned repo(s)...")
                for clone_path in clones:
                    if remove_clone_dir(clone_path):
                        logger.info("Removed clone: %s", clone_path)
                    else:
                        logger.warning(
                            "Failed to remove clone %s (file may be in use)",
                            clone_path,
                        )
                clear_clone_registry()
