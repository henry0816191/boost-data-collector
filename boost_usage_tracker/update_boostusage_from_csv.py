"""
Load add_to_boostUsage.csv and update BoostUsage table.

CSV columns: owner, repo_name, file_path, boost_header_name, last_commit_ts, excepted_at.

- Get repo (BoostExternalRepository) from owner + repo_name.
- Get file_path (GitHubFile) from repo_id + file_path.
- Get boost_header (BoostFile) from BoostFile table by boost_header_name (linked GitHubFile.filename).
- Create or update BoostUsage (repo, boost_header, file_path, last_commit_date).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from django.utils.dateparse import parse_datetime

from config.workspace import get_workspace_path
from boost_library_tracker.models import BoostFile
from boost_usage_tracker.models import BoostExternalRepository
from boost_usage_tracker.services import (
    create_or_update_boost_usage,
    mark_usages_excepted_bulk,
)
from github_activity_tracker.models import GitHubFile

logger = logging.getLogger(__name__)

DEFAULT_CSV_FILENAME = "add_to_boostUsage.csv"


def _parse_datetime(value: Any):
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return parse_datetime(str(value).strip())


def get_boostusage_csv_path() -> Path:
    """Return workspace/boost_usage_tracker/add_to_boostUsage.csv."""
    return get_workspace_path("boost_usage_tracker") / DEFAULT_CSV_FILENAME


def update_boostusage_table_from_csv(
    source: str | Path | None = None,
) -> dict[str, Any]:
    """Read CSV and add/update BoostUsage rows.

    For each row: resolve repo (BoostExternalRepository) by owner+repo_name;
    resolve file_path (GitHubFile) by repo+file_path; resolve boost_header (BoostFile)
    by boost_header_name; then create_or_update_boost_usage.

    Args:
        source: Path to CSV file. Default: workspace/boost_usage_tracker/add_to_boostUsage.csv.

    Returns:
        Dict with keys: source_path, created, updated, skipped_no_repo, skipped_no_file,
        skipped_no_boost_header, errors.
    """
    path = Path(source) if source is not None else get_boostusage_csv_path()
    result: dict[str, Any] = {
        "source_path": str(path),
        "created": 0,
        "updated": 0,
        "skipped_no_repo": 0,
        "skipped_no_file": 0,
        "skipped_no_boost_header": 0,
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append(f"File not found: {path}")
        return result

    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            to_except = []
            reader = csv.DictReader(f)
            required = ("owner", "repo_name", "file_path", "boost_header_name")
            if not reader.fieldnames or not all(
                col in reader.fieldnames for col in required
            ):
                result["errors"].append(f"CSV must have columns: {', '.join(required)}")
                return result
            for row in reader:
                owner = (row.get("owner") or "").strip()
                repo_name = (row.get("repo_name") or "").strip()
                file_path = (row.get("file_path") or "").strip()
                boost_header_name = (row.get("boost_header_name") or "").strip()
                if not owner or not repo_name or not file_path or not boost_header_name:
                    continue
                repo = BoostExternalRepository.objects.filter(
                    owner_account__username=owner,
                    repo_name=repo_name,
                ).first()
                if repo is None:
                    result["skipped_no_repo"] += 1
                    logger.debug(
                        "Skipping: no repo for owner=%r repo_name=%r", owner, repo_name
                    )
                    continue
                file_path_obj = GitHubFile.objects.filter(
                    repo_id=repo.pk,
                    filename=file_path,
                ).first()
                if file_path_obj is None:
                    result["skipped_no_file"] += 1
                    logger.debug(
                        "Skipping: no GitHubFile for repo_id=%s file_path=%r",
                        repo.pk,
                        file_path,
                    )
                    continue
                boost_header = BoostFile.objects.filter(
                    github_file__filename=boost_header_name,
                ).first()
                if boost_header is None:
                    result["skipped_no_boost_header"] += 1
                    logger.debug(
                        "Skipping: no BoostFile for boost_header_name=%r",
                        boost_header_name,
                    )
                    continue
                last_commit_ts = row.get("last_commit_ts")
                last_commit_date = (
                    _parse_datetime(last_commit_ts) if last_commit_ts else None
                )
                usage, created = create_or_update_boost_usage(
                    repo,
                    boost_header=boost_header,
                    file_path=file_path_obj,
                    last_commit_date=last_commit_date,
                )
                if created:
                    result["created"] += 1
                else:
                    result["updated"] += 1
                if (row.get("excepted_at") or "").strip():
                    to_except.append(usage.pk)
            if to_except:
                mark_usages_excepted_bulk(to_except)
    except (OSError, csv.Error) as e:
        result["errors"].append(str(e))
    return result
