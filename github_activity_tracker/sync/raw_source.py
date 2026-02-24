"""
Tmp: save/update JSON in workspace/raw/github_activity_tracker. Will be removed in product.

- Commits: write once (no merge).
- Issues/PRs: load existing file if any, merge by id for comments/reviews so updated
  comments or reviews are not lost, then write.
"""

from __future__ import annotations

import json
from pathlib import Path

from github_activity_tracker.workspace import (
    get_raw_source_commit_path,
    get_raw_source_issue_path,
    get_raw_source_pr_path,
)


def _merge_list_by_id(existing_list: list, new_list: list, id_key: str = "id") -> list:
    """Merge two lists of dicts by id; new wins for same id. Preserve order: existing then new (by id)."""
    by_id: dict = {}
    for item in existing_list or []:
        kid = item.get(id_key)
        if kid is not None:
            by_id[kid] = item
    for item in new_list or []:
        kid = item.get(id_key)
        if kid is not None:
            by_id[kid] = item
    # Order: existing order for pre-existing ids, then new ids in new order
    order_ids = list(
        dict.fromkeys(
            [x.get(id_key) for x in (existing_list or []) if x.get(id_key) is not None]
        )
    )
    for x in new_list or []:
        kid = x.get(id_key)
        if kid is not None and kid not in order_ids:
            order_ids.append(kid)
    return [by_id[kid] for kid in order_ids if kid in by_id]


def _merge_issue_json(existing: dict, new: dict) -> dict:
    """Merge issue JSON: top-level from new; comments merged by id so we keep all/updated comments."""
    merged = {**new}
    merged["comments"] = _merge_list_by_id(
        existing.get("comments") or [],
        new.get("comments") or [],
        "id",
    )
    return merged


def _merge_pr_json(existing: dict, new: dict) -> dict:
    """Merge PR JSON: top-level from new; comments and reviews merged by id."""
    merged = {**new}
    merged["comments"] = _merge_list_by_id(
        existing.get("comments") or [],
        new.get("comments") or [],
        "id",
    )
    merged["reviews"] = _merge_list_by_id(
        existing.get("reviews") or [],
        new.get("reviews") or [],
        "id",
    )
    return merged


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def save_commit_raw_source(owner: str, repo: str, commit_data: dict) -> None:
    """Save commit JSON to raw/github_activity_tracker (no merge; overwrite)."""
    path = get_raw_source_commit_path(owner, repo, commit_data.get("sha", ""))
    if not path.name or path.name == ".json":
        return
    _write_json(path, commit_data)


def save_issue_raw_source(owner: str, repo: str, issue_data: dict) -> None:
    """Load existing issue JSON if present, merge comments by id, then write."""
    raw = issue_data.get("number") or issue_data.get("issue_info", {}).get("number")
    if raw is None:
        return
    if isinstance(raw, int):
        number = raw
    elif isinstance(raw, str) and raw.isdigit():
        number = int(raw)
    else:
        return
    if number <= 0:
        return
    path = get_raw_source_issue_path(owner, repo, number)
    if not path.name or path.name == ".json":
        return
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    merged = _merge_issue_json(existing, issue_data)
    _write_json(path, merged)


def save_pr_raw_source(owner: str, repo: str, pr_data: dict) -> None:
    """Load existing PR JSON if present, merge comments and reviews by id, then write."""
    raw = pr_data.get("number") or pr_data.get("pr_info", {}).get("number")
    if raw is None:
        return
    if isinstance(raw, int):
        number = raw
    elif isinstance(raw, str) and raw.isdigit():
        number = int(raw)
    else:
        return
    if number <= 0:
        return
    path = get_raw_source_pr_path(owner, repo, number)
    if not path.name or path.name == ".json":
        return
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    merged = _merge_pr_json(existing, pr_data)
    _write_json(path, merged)
