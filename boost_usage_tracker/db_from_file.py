"""
Load data from JSON files and update specified database tables.

Source for GitHubAccount: JSON files in workspace/boost_usage_tracker/github_account.
Each file may be a single JSON object or a JSON array of objects.

Expected fields per record:
  github_account_id  (int, required)
  username           (str, optional)
  display_name       (str, optional)
  avatar_url         (str, optional)
  account_type       ("user" | "organization" | "enterprise", optional)

Updates both GitHubAccount and BaseProfile via cppa_user_tracker.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config.workspace import get_workspace_path

logger = logging.getLogger(__name__)

_GITHUB_ACCOUNT_SUBDIR = "github_account"


def get_github_account_dir() -> Path:
    """Return workspace/boost_usage_tracker/github_account; creates dir if missing."""
    path = get_workspace_path("boost_usage_tracker") / _GITHUB_ACCOUNT_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_json_records_from_path(path: Path) -> list[dict[str, Any]]:
    """Load one or more records from a JSON file (single object or array)."""
    if path.stem.startswith("."):
        return []
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _load_all_json_records(dir_path: Path) -> list[dict[str, Any]]:
    """Load all records from every .json file in *dir_path* (recursive)."""
    records: list[dict[str, Any]] = []
    if not dir_path.is_dir():
        logger.warning("Directory does not exist: %s", dir_path)
        return records
    for path in sorted(dir_path.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            records.extend(_load_json_records_from_path(path))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping %s: %s", path.name, e)
    return records


def _normalize_account_type(value: Any) -> str:
    """Return a valid GitHubAccountType choice string; defaults to 'user'."""
    from cppa_user_tracker.models import GitHubAccountType

    if not value:
        return GitHubAccountType.USER
    s = str(value).strip().lower()
    if s in ("organization", "org"):
        return GitHubAccountType.ORGANIZATION
    if s == "enterprise":
        return GitHubAccountType.ENTERPRISE
    return GitHubAccountType.USER


def _update_github_account_from_records(
    records: list[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert GitHubAccount (and BaseProfile) for each record.

    Fields read from each record:
      ``github_account_id`` (int, required), ``username``, ``display_name``,
      ``avatar_url``, ``account_type``.

    Returns ``(created_count, updated_count)``.
    """
    from cppa_user_tracker.services import get_or_create_github_account

    created_count = 0
    updated_count = 0
    for rec in records:
        if not isinstance(rec, dict):
            logger.warning("Skipping record not a dictionary: %s", rec)
            continue
        raw_id = rec.get("github_account_id")
        if raw_id is None:
            logger.warning("Skipping record missing github_account_id: %s", rec)
            continue
        try:
            gid = int(raw_id)
        except (TypeError, ValueError):
            logger.warning("Skipping record with invalid github_account_id %r", raw_id)
            continue

        username = str(rec.get("username") or "").strip()
        display_name = str(rec.get("display_name") or "").strip()
        avatar_url = str(rec.get("avatar_url") or "").strip()
        account_type = _normalize_account_type(rec.get("account_type"))

        _, created = get_or_create_github_account(
            github_account_id=gid,
            username=username,
            display_name=display_name,
            avatar_url=avatar_url,
            account_type=account_type,
            identity=None,
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

    return created_count, updated_count


def update_db_from_file(
    source: str | Path | None = None,
    table: str = "github_account",
) -> dict[str, Any]:
    """Load data from a file or directory and update *table*.

    Args:
        source: Path to a ``.json`` file or a directory containing ``.json``
            files.  For ``"github_account"`` defaults to the workspace dir
            returned by :func:`get_github_account_dir`.
        table: Which table to update.  Currently supported: ``"github_account"``.

    Returns:
        Dict with keys ``table``, ``source_path``, ``created``, ``updated``,
        and optionally ``errors``.
    """
    path = Path(source) if source is not None else None

    if table == "github_account":
        if path is None:
            path = get_github_account_dir()

        if path.is_dir():
            records = _load_all_json_records(path)
        elif path.is_file() and path.suffix.lower() == ".json":
            records = _load_json_records_from_path(path)
        else:
            return {
                "table": table,
                "source_path": str(path),
                "created": 0,
                "updated": 0,
                "errors": ["Source is not a directory or a .json file"],
            }

        created, updated = _update_github_account_from_records(records)
        return {
            "table": table,
            "source_path": str(path),
            "created": created,
            "updated": updated,
        }

    return {
        "table": table,
        "source_path": str(path) if path else "",
        "created": 0,
        "updated": 0,
        "errors": [f"Unsupported table: {table}"],
    }
