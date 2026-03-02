"""
Load data from CSV or JSON files and update specified tables.

- Source for GitHubAccount: JSON files in workspace/boost_usage_tracker/github_account.
  Each file may be a single JSON object or a JSON array of objects. Each object
  should have github_account_id (required), and optionally username, display_name,
  avatar_url, account_type ("user" | "organization" | "enterprise").
  Updates both GitHubAccount and BaseProfile (via cppa_user_tracker).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config.workspace import get_workspace_path

logger = logging.getLogger(__name__)

# Subdir under boost_usage_tracker workspace for GitHub account JSON files
GITHUB_ACCOUNT_SUBDIR = "github_account"


def get_github_account_dir() -> Path:
    """Return workspace/boost_usage_tracker/github_account; creates dir if missing."""
    path = get_workspace_path("boost_usage_tracker") / GITHUB_ACCOUNT_SUBDIR
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
    """Load all records from every .json file in dir_path."""
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


def _normalize_github_account_type(value: Any) -> str:
    """Return valid GitHubAccountType value; default 'user'."""
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
    """Upsert GitHubAccount (and BaseProfile) for each record. Returns (created_count, updated_count)."""
    from cppa_user_tracker.services import get_or_create_github_account

    created_count = 0
    updated_count = 0
    for rec in records:
        owner = rec
        if "owner" in rec:
            owner = rec.get("owner")
        if not isinstance(owner, dict):
            logger.warning("Skipping record with invalid owner : %s", rec)
            continue
        github_account_id_raw = owner.get("id")
        if github_account_id_raw is None:
            logger.warning("Skipping record missing github_account_id: %s", owner)
            continue
        try:
            gid = int(github_account_id_raw)
        except (TypeError, ValueError):
            logger.warning(
                "Skipping record with invalid github_account_id %r",
                github_account_id_raw,
            )
            continue
        username = (owner.get("login") or "").strip() or ""
        display_name = (owner.get("name") or "").strip() or ""
        avatar_url = (owner.get("avatar_url") or "").strip() or ""
        account_type = _normalize_github_account_type(owner.get("type"))
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
        if username == "":
            logger.warning("Created record with empty username: %s", owner)
    return created_count, updated_count


def update_git_account(
    source: str | Path | None = None,
    table: str = "github_account",
) -> dict[str, Any]:
    """Load data from CSV or JSON and update the specified table.

    Args:
        source: Path to a file or directory. For table "github_account", defaults to
            workspace/boost_usage_tracker/github_account (directory of JSON files).
        table: Which table to update. Supported: "github_account" (updates GitHubAccount
            and BaseProfile via cppa_user_tracker).

    Returns:
        Dict with keys: table, source_path, created, updated, errors (optional).
    """
    path = Path(source) if source is not None else None
    if table == "github_account":
        if path is None:
            path = get_github_account_dir()
        if path.is_dir():
            records = _load_all_json_records(path)
        elif path.is_file() and path.suffix.lower() == ".json":
            try:
                records = _load_json_records_from_path(path)
            except (json.JSONDecodeError, OSError) as e:
                result = _result_template(table, str(path))
                result["errors"].append(f"Skipping {path.name}: {e}")
                return result
        else:
            result = _result_template(table, str(path))
            result["errors"].append("Source is not a directory or .json file")
            return result
        created, updated = _update_github_account_from_records(records)
        result = _result_template(table, str(path))
        result["created"] += created
        result["updated"] += updated
        return result
    result = _result_template(table, str(path) if path else None)
    result["errors"].append(f"Unsupported table: {table}")
    return result


def _result_template(table: str, source_path: str | None) -> dict[str, Any]:
    return {
        "table": table,
        "source_path": source_path,
        "created": 0,
        "updated": 0,
        "errors": [],
    }
