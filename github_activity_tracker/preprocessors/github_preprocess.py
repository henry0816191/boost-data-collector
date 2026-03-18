"""
Shared Pinecone preprocessing helpers for GitHub issues and PRs.

Reads raw JSON files from workspace/raw/github_activity_tracker/<owner>/<repo>/
and produces document dicts for cppa_pinecone_sync.sync.sync_to_pinecone.

Public API:
  Single-repo (used by clang_github_tracker):
    preprocess_issues(owner, repo, failed_ids, final_sync_at)
    preprocess_prs(owner, repo, failed_ids, final_sync_at)

  Multi-repo (used by boost_library_tracker):
    preprocess_all_issues(owner, failed_ids, final_sync_at)
    preprocess_all_prs(owner, failed_ids, final_sync_at)

Document dict shape (per docs/Pinecone_preprocess_guideline.md):
  {
    "content": <markdown string>,
    "metadata": {
      "doc_id": <html_url>,
      "ids": "<repo>:issue:<number>" or "<repo>:pr:<number>",
      "type": "issue" | "pr",
      "number": <int>,
      "title": <str>,
      "url": <str>,
      "author": <str>,
      "state": <str>,
      "created_at": <float timestamp>,
      "updated_at": <float timestamp>,
      "closed_at": <float timestamp>,
      "repo_name": <str>,
    },
  }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from operations.md_ops.issue_to_md import issue_json_to_md
from operations.md_ops.pr_to_md import pr_json_to_md

from github_activity_tracker.workspace import (
    get_raw_source_issues_dir,
    get_raw_source_prs_dir,
    get_raw_source_root,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _parse_updated_at(info: dict[str, Any]) -> datetime | None:
    """Parse updated_at ISO string from issue_info or pr_info. Returns UTC datetime or None."""
    raw = info.get("updated_at") or info.get("created_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _to_timestamp(iso_str: str | None) -> float:
    """Convert ISO datetime string to Unix timestamp float. Returns 0.0 if missing/invalid."""
    if not iso_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _file_modified_at(path: Path) -> datetime | None:
    """Return the file's modification time as UTC datetime, or None if not available."""
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except OSError:
        return None


def _iter_json_files(
    directory: Path,
) -> Generator[tuple[Path, dict[str, Any]], None, None]:
    """Yield (path, parsed_data) for each *.json in directory. Skips unreadable files."""
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Skipping %s: %s", path, exc)
            continue
        if isinstance(data, dict):
            yield path, data


# ---------------------------------------------------------------------------
# Public iterators
# ---------------------------------------------------------------------------


def iter_raw_repos(owner: str) -> Generator[str, None, None]:
    """Yield repo names (subdirectory names) under workspace/raw/github_activity_tracker/<owner>/."""
    owner_dir = get_raw_source_root() / owner
    if not owner_dir.is_dir():
        return
    for entry in sorted(owner_dir.iterdir()):
        if entry.is_dir():
            yield entry.name


def iter_raw_issue_jsons(
    owner: str, repo: str
) -> Generator[tuple[Path, dict[str, Any]], None, None]:
    """Yield (path, data) for each issue JSON under workspace/raw/.../issues/."""
    yield from _iter_json_files(get_raw_source_issues_dir(owner, repo))


def iter_raw_pr_jsons(
    owner: str, repo: str
) -> Generator[tuple[Path, dict[str, Any]], None, None]:
    """Yield (path, data) for each PR JSON under workspace/raw/.../prs/."""
    yield from _iter_json_files(get_raw_source_prs_dir(owner, repo))


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------


def build_issue_document(
    path: Path,
    data: dict[str, Any],
    repo: str,
) -> dict[str, Any] | None:
    """Build a Pinecone document dict from a raw issue JSON file.

    Returns None if issue_info is missing, html_url is absent, or content is empty.
    """
    info = data.get("issue_info")
    if not isinstance(info, dict):
        logger.debug("Skipping %s: no issue_info", path.name)
        return None

    html_url = (info.get("html_url") or "").strip()
    if not html_url:
        logger.debug("Skipping %s: no html_url", path.name)
        return None

    content = issue_json_to_md(data).strip()
    if not content:
        logger.debug("Skipping %s: empty markdown content", path.name)
        return None

    number = info.get("number") or -1
    return {
        "content": content,
        "metadata": {
            "doc_id": html_url,
            "ids": f"{repo}:issue:{number}",
            "type": "issue",
            "number": number,
            "title": (info.get("title") or "").strip(),
            "url": html_url,
            "author": (info.get("user") or {}).get("login", "") or "",
            "state": (info.get("state") or "").lower(),
            "state_reason": (info.get("state_reason") or "").lower(),
            "created_at": _to_timestamp(info.get("created_at")),
            "updated_at": _to_timestamp(info.get("updated_at")),
            "closed_at": _to_timestamp(info.get("closed_at")),
            "repo_name": repo,
        },
    }


def build_pr_document(
    path: Path,
    data: dict[str, Any],
    repo: str,
) -> dict[str, Any] | None:
    """Build a Pinecone document dict from a raw PR JSON file.

    Returns None if pr_info is missing, html_url is absent, or content is empty.
    """
    info = data.get("pr_info")
    if not isinstance(info, dict):
        logger.debug("Skipping %s: no pr_info", path.name)
        return None

    html_url = (info.get("html_url") or "").strip()
    if not html_url:
        logger.debug("Skipping %s: no html_url", path.name)
        return None

    content = pr_json_to_md(data).strip()
    if not content:
        logger.debug("Skipping %s: empty markdown content", path.name)
        return None

    number = info.get("number") or -1
    return {
        "content": content,
        "metadata": {
            "doc_id": html_url,
            "ids": f"{repo}:pr:{number}",
            "type": "pr",
            "number": number,
            "title": (info.get("title") or "").strip(),
            "url": html_url,
            "author": (info.get("user") or {}).get("login", "") or "",
            "state": (info.get("state") or "").lower(),
            "created_at": _to_timestamp(info.get("created_at")),
            "updated_at": _to_timestamp(info.get("updated_at")),
            "closed_at": _to_timestamp(info.get("closed_at")),
            "repo_name": repo,
        },
    }


# ---------------------------------------------------------------------------
# Single-repo preprocessors (used by clang_github_tracker)
# ---------------------------------------------------------------------------


def preprocess_issues(
    owner: str,
    repo: str,
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Build Pinecone documents for issues from one raw repo directory.

    Selects issues where:
      - updated_at > final_sync_at (incremental), OR
      - ids value is in failed_ids (retry)

    Args:
        owner: GitHub owner (e.g. "llvm").
        repo: Repository name (e.g. "llvm-project").
        failed_ids: Previously failed ids strings for retry.
        final_sync_at: Last successful sync timestamp; None means first run (sync all).

    Returns:
        (documents, is_chunked=False)
    """
    failed_set = set(failed_ids or [])
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path, data in iter_raw_issue_jsons(owner, repo):
        info = data.get("issue_info") or {}
        number = info.get("number") or -1
        ids_val = f"{repo}:issue:{number}"

        is_failed = ids_val in failed_set
        updated_at = _parse_updated_at(info)
        file_modified_at = _file_modified_at(path)
        is_new = final_sync_at is None or (
            (updated_at is not None and updated_at > final_sync_at)
            or (file_modified_at is not None and file_modified_at > final_sync_at)
        )

        if not is_failed and not is_new:
            continue

        if ids_val in seen:
            continue
        seen.add(ids_val)

        doc = build_issue_document(path, data, repo)
        if doc is not None:
            documents.append(doc)

    logger.info(
        "preprocess_issues: owner=%s repo=%s → %d documents",
        owner,
        repo,
        len(documents),
    )
    return documents, False


def preprocess_prs(
    owner: str,
    repo: str,
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Build Pinecone documents for PRs from one raw repo directory.

    Selects PRs where:
      - updated_at > final_sync_at (incremental), OR
      - ids value is in failed_ids (retry)

    Args:
        owner: GitHub owner (e.g. "llvm").
        repo: Repository name (e.g. "llvm-project").
        failed_ids: Previously failed ids strings for retry.
        final_sync_at: Last successful sync timestamp; None means first run (sync all).

    Returns:
        (documents, is_chunked=False)
    """
    failed_set = set(failed_ids or [])
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()

    for path, data in iter_raw_pr_jsons(owner, repo):
        info = data.get("pr_info") or {}
        number = info.get("number") or -1
        ids_val = f"{repo}:pr:{number}"

        is_failed = ids_val in failed_set
        updated_at = _parse_updated_at(info)
        file_modified_at = _file_modified_at(path)
        is_new = final_sync_at is None or (
            (updated_at is not None and updated_at > final_sync_at)
            or (file_modified_at is not None and file_modified_at > final_sync_at)
        )

        if not is_failed and not is_new:
            continue

        if ids_val in seen:
            continue
        seen.add(ids_val)

        doc = build_pr_document(path, data, repo)
        if doc is not None:
            documents.append(doc)

    logger.info(
        "preprocess_prs: owner=%s repo=%s → %d documents", owner, repo, len(documents)
    )
    return documents, False


# ---------------------------------------------------------------------------
# Multi-repo preprocessors (used by boost_library_tracker)
# ---------------------------------------------------------------------------


def preprocess_all_issues(
    owner: str,
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Build Pinecone documents for issues across all repos under owner.

    Iterates all subdirectories of workspace/raw/github_activity_tracker/<owner>/
    and calls preprocess_issues for each repo, merging results.

    Args:
        owner: GitHub owner (e.g. "boostorg").
        failed_ids: Previously failed ids strings for retry.
        final_sync_at: Last successful sync timestamp; None means first run.

    Returns:
        (documents, is_chunked=False)
    """
    all_documents: list[dict[str, Any]] = []
    for repo in iter_raw_repos(owner):
        docs, _ = preprocess_issues(owner, repo, failed_ids, final_sync_at)
        all_documents.extend(docs)

    logger.info(
        "preprocess_all_issues: owner=%s → %d total documents",
        owner,
        len(all_documents),
    )
    return all_documents, False


def preprocess_all_prs(
    owner: str,
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Build Pinecone documents for PRs across all repos under owner.

    Iterates all subdirectories of workspace/raw/github_activity_tracker/<owner>/
    and calls preprocess_prs for each repo, merging results.

    Args:
        owner: GitHub owner (e.g. "boostorg").
        failed_ids: Previously failed ids strings for retry.
        final_sync_at: Last successful sync timestamp; None means first run.

    Returns:
        (documents, is_chunked=False)
    """
    all_documents: list[dict[str, Any]] = []
    for repo in iter_raw_repos(owner):
        docs, _ = preprocess_prs(owner, repo, failed_ids, final_sync_at)
        all_documents.extend(docs)

    logger.info(
        "preprocess_all_prs: owner=%s → %d total documents", owner, len(all_documents)
    )
    return all_documents, False
