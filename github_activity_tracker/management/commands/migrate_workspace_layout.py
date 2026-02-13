"""
Migrate workspace/github_activity_tracker from the legacy layout to the app layout.

Legacy (current on disk):
  <owner>/commits/<repo>/master/<hash>.json   (preferred)
  <owner>/commits/<repo>/developer/<hash>.json  (used only if master/ is missing)
  <owner>/issues/<repo>/issue_<issue_number>.json
  <owner>/prs/<repo>/pr_<pr_number>.json

Target (app expects):
  <owner>/<repo>/commits/<hash>.json
  <owner>/<repo>/issues/<issue_number>.json
  <owner>/<repo>/prs/<pr_number>.json

Run: python manage.py migrate_workspace_layout
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

_ISSUE_PREFIX = "issue_"
_PR_PREFIX = "pr_"


class Command(BaseCommand):
    help = "Migrate github_activity_tracker workspace from legacy layout to <owner>/<repo>/commits|issues|prs/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be moved; do not change files.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        root = Path(settings.WORKSPACE_DIR) / "github_activity_tracker"
        if not root.is_dir():
            self.stdout.write(
                self.style.WARNING(f"Workspace root does not exist: {root}")
            )
            return

        moved = 0
        for owner_path in root.iterdir():
            if not owner_path.is_dir():
                continue
            # owner = owner_path.name

            # commits: owner/commits/<repo>/master/<hash>.json or .../developer/<hash>.json -> owner/<repo>/commits/<hash>.json
            # Prefer master; if master/ is missing, use developer/. Ignore developer when master exists.
            commits_legacy = owner_path / "commits"
            if commits_legacy.is_dir():
                for repo_path in commits_legacy.iterdir():
                    if not repo_path.is_dir():
                        continue
                    repo = repo_path.name
                    master_dir = repo_path / "master"
                    developer_dir = repo_path / "developer"
                    source_commits = (
                        master_dir
                        if master_dir.is_dir()
                        else developer_dir if developer_dir.is_dir() else None
                    )
                    if not source_commits or not source_commits.is_dir():
                        continue
                    dest_commits = owner_path / repo / "commits"
                    for f in source_commits.glob("*.json"):
                        dest = dest_commits / f.name
                        if dry_run:
                            self.stdout.write(
                                f"  would move: {f.relative_to(root)} -> {dest.relative_to(root)}"
                            )
                        else:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(f), str(dest))
                        moved += 1

            # issues: owner/issues/<repo>/issue_<n>.json -> owner/<repo>/issues/<n>.json
            issues_legacy = owner_path / "issues"
            if issues_legacy.is_dir():
                for repo_path in issues_legacy.iterdir():
                    if not repo_path.is_dir():
                        continue
                    repo = repo_path.name
                    dest_issues = owner_path / repo / "issues"
                    for f in repo_path.glob("issue_*.json"):
                        base = f.stem  # "issue_123"
                        if base.startswith(_ISSUE_PREFIX):
                            new_name = base[len(_ISSUE_PREFIX) :] + ".json"
                        else:
                            new_name = f.name
                        dest = dest_issues / new_name
                        if dry_run:
                            self.stdout.write(
                                f"  would move: {f.relative_to(root)} -> {dest.relative_to(root)}"
                            )
                        else:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(f), str(dest))
                        moved += 1

            # prs: owner/prs/<repo>/pr_<n>.json -> owner/<repo>/prs/<n>.json
            prs_legacy = owner_path / "prs"
            if prs_legacy.is_dir():
                for repo_path in prs_legacy.iterdir():
                    if not repo_path.is_dir():
                        continue
                    repo = repo_path.name
                    dest_prs = owner_path / repo / "prs"
                    for f in repo_path.glob("pr_*.json"):
                        base = f.stem  # "pr_45"
                        if base.startswith(_PR_PREFIX):
                            new_name = base[len(_PR_PREFIX) :] + ".json"
                        else:
                            new_name = f.name
                        dest = dest_prs / new_name
                        if dry_run:
                            self.stdout.write(
                                f"  would move: {f.relative_to(root)} -> {dest.relative_to(root)}"
                            )
                        else:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(f), str(dest))
                        moved += 1

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Dry run: {moved} file(s) would be moved.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Moved {moved} file(s) to app layout.")
            )
