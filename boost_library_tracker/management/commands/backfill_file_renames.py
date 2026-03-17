"""
Backfill previous_filename_id for renamed files in GitHubFile model.

Scans all commit JSON files in workspace/raw/github_activity_tracker/boostorg/
to find renamed files and populate the previous_filename_id field.

Run: python manage.py backfill_file_renames [--dry-run] [--limit N] [--repo REPO]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from github_activity_tracker.models import GitHubRepository, GitHubFile
from github_activity_tracker.services import set_github_file_previous_filename

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Backfill previous_filename_id for renamed files by scanning "
        "raw commit JSON files in workspace/raw/github_activity_tracker/boostorg/"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only list renames that would be updated; do not change the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            metavar="N",
            help="Process at most N commits (0 = no limit).",
        )
        parser.add_argument(
            "--repo",
            type=str,
            default="",
            metavar="REPO",
            help="Only process commits for a specific boostorg repo (e.g., 'math', 'accumulators').",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        repo_filter = options["repo"]

        # Base path for raw commit JSONs
        workspace_base = Path("workspace/raw/github_activity_tracker/boostorg")
        if not workspace_base.exists():
            self.stdout.write(
                self.style.ERROR(f"Workspace directory not found: {workspace_base}")
            )
            return

        # Find all repo directories
        repo_dirs = [d for d in workspace_base.iterdir() if d.is_dir()]
        if repo_filter:
            repo_dirs = [d for d in repo_dirs if d.name == repo_filter]
            if not repo_dirs:
                self.stdout.write(
                    self.style.ERROR(
                        f"Repository '{repo_filter}' not found in {workspace_base}"
                    )
                )
                return

        self.stdout.write(
            f"Scanning {len(repo_dirs)} repository/repositories in {workspace_base}"
        )

        total_commits = 0
        total_renames = 0
        total_updated = 0
        total_failed = 0
        skipped_repos = 0
        failed_renames: list[tuple[str, str, str, str]] = []  # (repo, prev, new, error)

        for repo_dir in sorted(repo_dirs):
            repo_name = repo_dir.name
            commits_dir = repo_dir / "commits"

            if not commits_dir.exists():
                self.stdout.write(
                    self.style.WARNING(f"  Skipping {repo_name}: no commits directory")
                )
                continue

            # Get GitHubRepository from database
            try:
                repo = GitHubRepository.objects.select_related("owner_account").get(
                    owner_account__username="boostorg",
                    repo_name=repo_name,
                )
            except GitHubRepository.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping {repo_name}: repository not found in database"
                    )
                )
                skipped_repos += 1
                continue

            self.stdout.write(f"\nProcessing repository: {repo_name}")

            # Get all commit JSON files
            commit_files = sorted(commits_dir.glob("*.json"))
            if limit > 0:
                commit_files = commit_files[:limit]

            repo_commits = 0
            repo_renames = 0
            repo_updated = 0
            repo_failed = 0

            for commit_file in commit_files:
                try:
                    with open(commit_file, "r", encoding="utf-8") as f:
                        commit_data = json.load(f)

                    repo_commits += 1
                    total_commits += 1

                    # Process files in commit
                    files = commit_data.get("files", [])
                    for file_info in files:
                        status = file_info.get("status", "").strip().lower()
                        if status != "renamed":
                            continue

                        filename = file_info.get("filename")
                        previous_filename = file_info.get("previous_filename")

                        if not filename or not previous_filename:
                            continue

                        filename = filename.strip()
                        previous_filename = previous_filename.strip()
                        repo_renames += 1
                        total_renames += 1

                        if dry_run:
                            self.stdout.write(
                                f"    Would link: {previous_filename} -> {filename}"
                            )
                        else:
                            # Update database
                            try:
                                with transaction.atomic():
                                    old_file, _ = GitHubFile.objects.get_or_create(
                                        repo=repo,
                                        filename=previous_filename,
                                        defaults={"is_deleted": False},
                                    )
                                    new_file, _ = GitHubFile.objects.get_or_create(
                                        repo=repo,
                                        filename=filename,
                                        defaults={"is_deleted": False},
                                    )

                                    # Only update if not already set
                                    if new_file.previous_filename_id != old_file.id:
                                        set_github_file_previous_filename(
                                            new_file, old_file
                                        )
                                        repo_updated += 1
                                        total_updated += 1
                                        logger.debug(
                                            "Linked %s -> %s in %s",
                                            previous_filename,
                                            filename,
                                            repo_name,
                                        )

                            except Exception as e:
                                repo_failed += 1
                                total_failed += 1
                                failed_renames.append(
                                    (repo_name, previous_filename, filename, str(e))
                                )
                                logger.exception(
                                    "Failed to update rename %s -> %s in %s: %s",
                                    previous_filename,
                                    filename,
                                    repo_name,
                                    e,
                                )
                                self.stdout.write(
                                    self.style.ERROR(
                                        f"    Error linking {previous_filename} -> {filename}: {e}"
                                    )
                                )

                    # Log progress every 100 commits
                    if repo_commits % 100 == 0:
                        self.stdout.write(
                            f"  Processed {repo_commits} commits, found {repo_renames} renames"
                        )

                except Exception as e:
                    logger.exception(
                        "Failed to process commit file %s: %s", commit_file, e
                    )
                    self.stdout.write(
                        self.style.ERROR(f"  Error processing {commit_file.name}: {e}")
                    )

            self.stdout.write(
                self.style.SUCCESS(
                    f"  Finished {repo_name}: {repo_commits} commits, "
                    f"{repo_renames} renames found, {repo_updated} updated, {repo_failed} failed"
                )
            )

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(
            self.style.SUCCESS(
                f"Total: {total_commits} commits processed, "
                f"{total_renames} renames found"
            )
        )
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run: no changes made. Run without --dry-run to apply updates."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"{total_updated} file renames updated in database")
            )
            if total_failed > 0:
                self.stdout.write(
                    self.style.ERROR(f"{total_failed} file renames failed")
                )
                self.stdout.write("")
                self.stdout.write(self.style.ERROR("Not linked (failed):"))
                for rname, prev, new, err in failed_renames:
                    self.stdout.write(f"  {rname}: {prev} -> {new}")
                    self.stdout.write(f"    ({err})")

        if skipped_repos > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"{skipped_repos} repositories skipped (not found in database)"
                )
            )
