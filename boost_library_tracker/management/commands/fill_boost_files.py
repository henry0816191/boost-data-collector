"""
Management command: fill_boost_files

For each Boost repository, picks one library and links all unlinked files to it:
- If the repo has exactly one BoostLibrary, use it.
- If the repo is "math" and has many libraries, use the one whose name matches
  "math" (e.g. library "Math"). Other multi-library repos are skipped.

Writes the list of files that still have no library to
workspace/boost_library_tracker/missing_library_files.csv and prints a summary.
"""

import csv
import logging

from django.core.management.base import BaseCommand

from boost_library_tracker.models import (
    BoostLibrary,
    BoostLibraryRepository,
)
from boost_library_tracker.services import get_or_create_boost_file
from config.workspace import get_workspace_path
from github_activity_tracker.models import GitHubFile

logger = logging.getLogger(__name__)


def _normalize_name(s: str) -> str:
    """Normalize for comparison: lower, strip, spaces and slashes to underscore."""
    if not s:
        return ""
    return s.strip().lower().replace(" ", "_").replace("/", "_")


class Command(BaseCommand):
    """Link unlinked repo files to the single library per repo; write missing files to CSV."""

    help = (
        "Link unlinked repo files to the one library: single-library repos use it; "
        "math repo with many libraries uses the library named Math."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report what would be done; do not create BoostFile records.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write("Dry run: no DB writes.")

        stats = {
            "repos_processed": 0,
            "repos_with_library": 0,
            "files_linked": 0,
        }

        for repo in BoostLibraryRepository.objects.all():
            stats["repos_processed"] += 1
            libraries = list(repo.libraries.all())
            if not libraries:
                continue
            repo_key = _normalize_name(repo.repo_name)
            if len(libraries) == 1:
                library = libraries[0]
            else:
                # Only for math repo: many libraries → use the one whose name matches "math"
                if repo_key != "math":
                    continue
                matching = [
                    lib for lib in libraries if _normalize_name(lib.name) == "math"
                ]
                if not matching:
                    continue
                library = matching[0]
            stats["repos_with_library"] += 1
            # Only process files that do not already belong to any library
            for github_file in repo.files.filter(
                is_deleted=False, boost_file__isnull=True
            ):
                if dry_run:
                    stats["files_linked"] += 1
                    continue
                get_or_create_boost_file(github_file, library)
                stats["files_linked"] += 1

        self.stdout.write(
            f"Repos processed: {stats['repos_processed']}, "
            f"repos with chosen library: {stats['repos_with_library']}, "
            f"files linked: {stats['files_linked']}"
        )

        # Files in Boost repos that have at least one library but this file has no BoostFile
        # (exclude files in repos that have zero libraries)
        boost_repos_with_library_ids = list(
            BoostLibrary.objects.values_list("repo_id", flat=True).distinct()
        )
        files_without_library = (
            GitHubFile.objects.filter(
                repo_id__in=boost_repos_with_library_ids, is_deleted=False
            )
            .filter(boost_file__isnull=True)
            .select_related("repo")
            .order_by("repo_id", "filename")
        )

        missing_count = files_without_library.count()
        csv_dir = get_workspace_path("boost_library_tracker")
        csv_path = csv_dir / "missing_library_files.csv"
        csv_columns = ("repo_id", "repo_name", "file_name")

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns)
            writer.writeheader()
            for gf in files_without_library:
                writer.writerow(
                    {
                        "repo_id": gf.repo_id,
                        "repo_name": gf.repo.repo_name if gf.repo_id else "",
                        "file_name": gf.filename,
                    }
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"Files without a library (in repos that have ≥1 library): {missing_count}"
            )
        )
        self.stdout.write(f"Wrote {missing_count} row(s) to {csv_path}")

        self.stdout.write(self.style.SUCCESS("Done."))
