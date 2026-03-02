"""
Management command: import_boost_file_from_csv

Reads a CSV of files (columns: library_name, file_name). Finds BoostLibrary by
library_name, then uses library.repo for the repository. Links existing
GitHubFile (by file_name) to BoostLibrary via BoostFile. Writes rows where the
library is not found or the file is not found to an error CSV (library_vs_header_errors.csv).
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand

from boost_library_tracker.models import BoostLibrary
from boost_library_tracker.services import get_or_create_boost_file

logger = logging.getLogger(__name__)

ERROR_CSV_COLUMNS = (
    "library_name",
    "file_name",
    "path_not_found",
    "library_not_found",
    "supported_files",  # when path not found: repo filenames that contain path (comma-separated)
)

# Map CSV library name (normalized: lower, spaces → underscore) to BoostLibrary.name in DB.
# Built from library_vs_header_errors.csv library_not_found values → real names (id,name,repo_id).
CSV_LIBRARY_NAME_TO_REAL_NAME = {
    "string_algo": "String Algo",
    "member_function": "Member Function",
    "enable_if": "Enable If",
    "swap": "Swap",
    "ref": "Ref",
    "functional_factory": "Functional/Factory",
    "functional_forward": "Functional/Forward",
    "functional_overloaded_function": "Functional/Overloaded Function",
    "tribool": "Tribool",
    "compressed_pair": "Compressed Pair",
    "identity_type": "Identity Type",
    "in_place_factory": "In Place Factory, Typed In Place Factory",
    "operators": "Operators",
    "result_of": "Result Of",
    "string_view": "String View",
    "value_initialized": "Value Initialized",
    "interval": "Interval",
    "odeint": "Odeint",
    "ublas": "uBLAS",
}


def _norm(s: str) -> str:
    """Return the string stripped of leading/trailing whitespace, or empty string if None."""
    return (s or "").strip()


def _resolve_library_name(csv_library_name: str) -> str:
    """Return the real BoostLibrary name; use mapping if CSV name differs from DB name."""
    key = (csv_library_name or "").strip().lower().replace(" ", "_")
    return CSV_LIBRARY_NAME_TO_REAL_NAME.get(key, csv_library_name.strip())


def _read_csv_rows(csv_path: Path):
    """Yield dicts for each row; skip empty or invalid rows. Only file_name is used for linking."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {
                k.strip().lower().replace(" ", "_"): v
                for k, v in row.items()
                if k is not None
            }
            library_name = _norm(row_lower.get("library_name"))
            file_name = _norm(row_lower.get("file_name"))
            if not library_name:
                continue
            yield {
                "library_name": library_name,
                "file_name": file_name,
            }


def _link_file_for_path(
    repo, library, path: str, stats: dict, error_rows: list, row: dict
) -> None:
    """Find existing GitHubFile by repo+path; if found link BoostFile, else append to error_rows."""
    if not path:
        return
    github_file = repo.files.filter(filename=path).first()
    if github_file is None:
        search_path = (
            path.removeprefix("include") if path.startswith("include") else path
        )
        support_files = repo.files.filter(filename__icontains=search_path).values_list(
            "filename", flat=True
        )
        support_filenames = [str(f) for f in support_files if f is not None]
        stats["files_not_found"] += 1
        if support_filenames:
            error_rows.append(
                {
                    "library_name": row["library_name"],
                    "file_name": row["file_name"],
                    "path_not_found": path,
                    "library_not_found": "",
                    "supported_files": ",".join(support_filenames),
                }
            )
        else:
            error_rows.append(
                {
                    "library_name": row["library_name"],
                    "file_name": row["file_name"],
                    "path_not_found": path,
                    "library_not_found": "",
                    "supported_files": "",
                }
            )
        return
    get_or_create_boost_file(github_file, library)
    stats["files_added"] += 1


class Command(BaseCommand):
    """Link existing GitHubFile rows to BoostLibrary via BoostFile using a CSV of library_name, file_name."""

    help = (
        "Link existing GitHubFile to BoostLibrary via BoostFile. CSV: library_name, file_name. "
        "Finds repo from BoostLibrary table by library_name. Writes missing-library and missing-file rows to an error CSV."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=Path,
            help="Path to the CSV file with columns library_name, file_name (e.g. workspace/boost_library_tracker/library_vs_header.csv)",
        )
        parser.add_argument(
            "--errors",
            type=Path,
            default=None,
            help="Path for CSV of rows where library or file was not found (default: <csv_file>_errors.csv)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only read CSV and report what would be done; do not write to DB.",
        )

    def handle(self, *_args, **options):
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
            real_name = _resolve_library_name(library_name)

            matches = list(BoostLibrary.objects.filter(name=real_name)[:2])
            if not matches:
                stats["skipped_no_library"] += 1
                if stats["skipped_no_library"] <= 3:
                    logger.debug("No BoostLibrary with name=%s", library_name)
                error_rows.append(
                    {
                        "library_name": library_name,
                        "file_name": file_name,
                        "path_not_found": "",
                        "library_not_found": library_name,
                        "supported_files": "",
                    }
                )
                continue
            if len(matches) > 1:
                stats["skipped_no_library"] += 1
                error_rows.append(
                    {
                        "library_name": library_name,
                        "file_name": file_name,
                        "path_not_found": "",
                        "library_not_found": f"{library_name} (ambiguous)",
                        "supported_files": "",
                    }
                )
                continue
            library = matches[0]

            repo = library.repo

            if dry_run:
                if file_name:
                    github_file = repo.files.filter(filename=file_name).first()
                    if github_file:
                        stats["files_added"] += 1
                    else:
                        stats["files_not_found"] += 1
                        error_rows.append(
                            {
                                **row,
                                "path_not_found": file_name,
                                "library_not_found": "",
                                "supported_files": "",
                            }
                        )
                continue

            if file_name:
                _link_file_for_path(repo, library, file_name, stats, error_rows, row)

        if error_rows:
            with open(errors_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=ERROR_CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(error_rows)
            self.stdout.write(
                self.style.WARNING(
                    f"Wrote {len(error_rows)} error row(s) to {errors_path}"
                )
            )

        self.stdout.write(
            f"Rows processed: {stats['rows']}, files linked: {stats['files_added']}, "
            f"files not found: {stats['files_not_found']}, skipped (no library): {stats['skipped_no_library']}"
        )
        self.stdout.write(self.style.SUCCESS("Done."))
