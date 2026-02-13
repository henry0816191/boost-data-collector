"""
Management command: import_boost_file_from_csv

Reads a CSV of files (columns: library_name, file_name, full_file_name). Finds
BoostLibrary by library_name, then uses library.repo for the repository. Links
existing GitHubFile to BoostLibrary via BoostFile. Writes rows where the file
is not found to an error CSV.
"""
import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand

from boost_library_tracker.models import BoostLibrary
from boost_library_tracker.services import get_or_create_boost_file

logger = logging.getLogger(__name__)

ERROR_CSV_COLUMNS = ("library_name", "file_name", "full_file_name", "path_not_found")


def _norm(s: str) -> str:
    return (s or "").strip()


def _read_csv_rows(csv_path: Path):
    """Yield dicts for each row; skip empty or invalid rows."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {k.strip().lower().replace(" ", "_"): v for k, v in row.items()}
            library_name = _norm(row_lower.get("library_name"))
            file_name = _norm(row_lower.get("file_name"))
            full_file_name = _norm(row_lower.get("full_file_name")) or file_name
            if not library_name:
                continue
            yield {
                "library_name": library_name,
                "file_name": file_name,
                "full_file_name": full_file_name,
            }


def _link_file_for_path(repo, library, path: str, stats: dict, error_rows: list, row: dict) -> None:
    """Find existing GitHubFile by repo+path; if found link BoostFile, else append to error_rows."""
    if not path:
        return
    github_file = repo.files.filter(filename=path).first()
    if github_file is None:
        error_rows.append({
            "library_name": row["library_name"],
            "file_name": row["file_name"],
            "full_file_name": row["full_file_name"],
            "path_not_found": path,
        })
        stats["files_not_found"] += 1
        return
    get_or_create_boost_file(github_file, library)
    stats["files_added"] += 1


class Command(BaseCommand):
    help = (
        "Link existing GitHubFile to BoostLibrary via BoostFile. CSV: library_name, file_name, full_file_name. "
        "Finds repo from BoostLibrary table by library_name. Writes missing-file rows to an error CSV."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=Path,
            help="Path to the CSV file (e.g. workspace/boost_library_tracker/library_vs_header.csv)",
        )
        parser.add_argument(
            "--errors",
            type=Path,
            default=None,
            help="Path for CSV of rows where file was not found in GitHubFile (default: <csv_file>_errors.csv)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only read CSV and report what would be done; do not write to DB.",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_file"]
        errors_path = options.get("errors")
        dry_run = options["dry_run"]

        if not csv_path.exists():
            self.stdout.write(self.style.ERROR(f"File not found: {csv_path}"))
            return

        if errors_path is None:
            errors_path = csv_path.parent / f"{csv_path.stem}_errors.csv"

        if dry_run:
            self.stdout.write("Dry run: no DB writes.")

        stats = {
            "rows": 0,
            "files_added": 0,
            "files_not_found": 0,
            "skipped_no_library": 0,
        }
        error_rows = []

        for row in _read_csv_rows(csv_path):
            stats["rows"] += 1
            library_name = row["library_name"]
            file_name = row["file_name"]
            full_file_name = row["full_file_name"]

            library = BoostLibrary.objects.filter(name=library_name).first()
            if not library:
                stats["skipped_no_library"] += 1
                if stats["skipped_no_library"] <= 3:
                    logger.debug("No BoostLibrary with name=%s", library_name)
                continue

            repo = library.repo

            if dry_run:
                if file_name:
                    github_file = repo.files.filter(filename=file_name).first()
                    if github_file:
                        stats["files_added"] += 1
                    else:
                        stats["files_not_found"] += 1
                        error_rows.append({
                            **row,
                            "path_not_found": file_name,
                        })
                if full_file_name and full_file_name != file_name:
                    github_file = repo.files.filter(filename=full_file_name).first()
                    if github_file:
                        stats["files_added"] += 1
                    else:
                        stats["files_not_found"] += 1
                        error_rows.append({
                            **row,
                            "path_not_found": full_file_name,
                        })
                continue

            if file_name:
                _link_file_for_path(
                    repo, library, file_name, stats, error_rows, row
                )
            if full_file_name and full_file_name != file_name:
                _link_file_for_path(
                    repo, library, full_file_name, stats, error_rows, row
                )

        if error_rows:
            with open(errors_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=ERROR_CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(error_rows)
            self.stdout.write(
                self.style.WARNING(f"Wrote {len(error_rows)} missing-file row(s) to {errors_path}")
            )

        self.stdout.write(
            f"Rows processed: {stats['rows']}, files linked: {stats['files_added']}, "
            f"files not found: {stats['files_not_found']}, skipped (no library): {stats['skipped_no_library']}"
        )
        self.stdout.write(self.style.SUCCESS("Done."))
