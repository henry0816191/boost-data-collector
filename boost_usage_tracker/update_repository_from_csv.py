"""
Load add_to_boostExternalRepository.csv and update GitHubRepository and BoostExternalRepository.

CSV columns: owner, repo_name, stars, forks,description, repo_pushed_at, repo_created_at,
repo_updated_at, boost_version, is_boost_embedded, is_boost_used.

- Resolves owner to GitHubAccount (by username); skips rows if owner not found.
- Creates/updates GitHubRepository (github_activity_tracker).
- Creates/updates BoostExternalRepository (boost_usage_tracker, extends GitHubRepository).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from django.utils.dateparse import parse_datetime

from config.workspace import get_workspace_path
from cppa_user_tracker.models import GitHubAccount
from github_activity_tracker.services import get_or_create_repository
from boost_usage_tracker.services import get_or_create_boost_external_repo

logger = logging.getLogger(__name__)

DEFAULT_CSV_FILENAME = "add_to_boostExternalRepository.csv"


def _parse_int(value: Any, default: int = 0) -> int:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in ("", "0", "false", "no"):
        return False
    return True


def _parse_datetime(value: Any):
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return parse_datetime(str(value).strip())


def get_repository_csv_path() -> Path:
    """Return workspace/boost_usage_tracker/add_to_boostExternalRepository.csv."""
    return get_workspace_path("boost_usage_tracker") / DEFAULT_CSV_FILENAME


def update_repository_table_from_csv(
    source: str | Path | None = None,
) -> dict[str, Any]:
    """Read CSV and update GitHubRepository and BoostExternalRepository.

    Args:
        source: Path to CSV file. Default: workspace/boost_usage_tracker/add_to_boostExternalRepository.csv.

    Returns:
        Dict with keys: source_path, created_repos, updated_repos, created_ext, updated_ext, skipped_no_owner, errors.
    """
    path = Path(source) if source is not None else get_repository_csv_path()
    result: dict[str, Any] = {
        "source_path": str(path),
        "created_repos": 0,
        "updated_repos": 0,
        "created_ext": 0,
        "updated_ext": 0,
        "skipped_no_owner": 0,
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
            ):
                result["errors"].append("CSV must have 'owner' and 'repo_name' columns")
                return result
            for row in reader:
                owner = (row.get("owner") or "").strip()
                repo_name = (row.get("repo_name") or "").strip()
                if not owner or not repo_name:
                    continue
                account = GitHubAccount.objects.filter(username=owner).first()
                if account is None:
                    result["skipped_no_owner"] += 1
                    logger.debug("Skipping row: no GitHubAccount for owner=%r", owner)
                    continue
                defaults: dict[str, Any] = {}
                if "stars" in row:
                    defaults["stars"] = _parse_int(row["stars"])
                if "forks" in row:
                    defaults["forks"] = _parse_int(row["forks"])
                if "description" in row and (row["description"] or "").strip() != "":
                    defaults["description"] = (row["description"] or "").strip()
                for key in ("repo_pushed_at", "repo_created_at", "repo_updated_at"):
                    if key in row:
                        dt = _parse_datetime(row[key])
                        if dt is not None:
                            defaults[key] = dt
                repo, repo_created = get_or_create_repository(
                    account, repo_name, **defaults
                )
                if repo_created:
                    result["created_repos"] += 1
                else:
                    result["updated_repos"] += 1
                boost_version = (row.get("boost_version") or "").strip()
                is_boost_embedded = _parse_bool(row.get("is_boost_embedded"))
                is_boost_used = _parse_bool(row.get("is_boost_used"))
                _, ext_created = get_or_create_boost_external_repo(
                    repo,
                    boost_version=boost_version,
                    is_boost_embedded=is_boost_embedded,
                    is_boost_used=is_boost_used,
                )
                if ext_created:
                    result["created_ext"] += 1
                else:
                    result["updated_ext"] += 1
    except (OSError, csv.Error) as e:
        result["errors"].append(str(e))
    return result
