"""
Load add_to_githubFile.csv and update GitHubFile table.

CSV columns: owner, repo_name, file_path, is_deleted.

- Resolves repo_id from GitHubRepository by owner (owner_account.username) and repo_name.
- Creates/updates GitHubFile (repo, filename=file_path, is_deleted) via github_activity_tracker.services.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from config.workspace import get_workspace_path
from github_activity_tracker.models import GitHubRepository
from github_activity_tracker.services import create_or_update_github_file

logger = logging.getLogger(__name__)

DEFAULT_CSV_FILENAME = "add_to_githubFile.csv"


def _parse_bool(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in ("", "0", "false", "no"):
        return False
    return True


def get_githubfile_csv_path() -> Path:
    """Return workspace/boost_usage_tracker/add_to_githubFile.csv."""
    return get_workspace_path("boost_usage_tracker") / DEFAULT_CSV_FILENAME


def update_githubfile_table_from_csv(
    source: str | Path | None = None,
) -> dict[str, Any]:
    """Read CSV and add/update GitHubFile rows.

    For each row: look up GitHubRepository by owner (username) + repo_name;
    then create or update GitHubFile (repo, filename=file_path, is_deleted).

    Args:
        source: Path to CSV file. Default: workspace/boost_usage_tracker/add_to_githubFile.csv.

    Returns:
        Dict with keys: source_path, created, updated, skipped_no_repo, errors.
    """
    path = Path(source) if source is not None else get_githubfile_csv_path()
    result: dict[str, Any] = {
        "source_path": str(path),
        "created": 0,
        "updated": 0,
        "skipped_no_repo": 0,
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append(f"File not found: {path}")
        return result

    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if (
                not reader.fieldnames
                or "owner" not in reader.fieldnames
                or "repo_name" not in reader.fieldnames
                or "file_path" not in reader.fieldnames
            ):
                result["errors"].append(
                    "CSV must have 'owner', 'repo_name', and 'file_path' columns"
                )
                return result
            for row in reader:
                owner = (row.get("owner") or "").strip()
                repo_name = (row.get("repo_name") or "").strip()
                file_path = (row.get("file_path") or "").strip()
                if not owner or not repo_name or not file_path:
                    continue
                repo = GitHubRepository.objects.filter(
                    owner_account__username=owner,
                    repo_name=repo_name,
                ).first()
                if repo is None:
                    result["skipped_no_repo"] += 1
                    logger.debug(
                        "Skipping row: no GitHubRepository for owner=%r repo_name=%r",
                        owner,
                        repo_name,
                    )
                    continue
                is_deleted = _parse_bool(row.get("is_deleted", False))
                _, created = create_or_update_github_file(
                    repo,
                    filename=file_path,
                    is_deleted=is_deleted,
                )
                if created:
                    result["created"] += 1
                else:
                    result["updated"] += 1
    except (OSError, csv.Error) as e:
        result["errors"].append(str(e))
    return result
