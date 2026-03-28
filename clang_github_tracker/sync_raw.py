"""
Sync llvm/llvm-project to raw/github_activity_tracker only (no DB).

Uses github_activity_tracker.fetcher and raw_source; does not call services or persist to DB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from github_activity_tracker import fetcher
from github_activity_tracker.sync.raw_source import (
    save_commit_raw_source,
    save_issue_raw_source,
    save_pr_raw_source,
)
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException

from clang_github_tracker import state_manager as clang_state
from clang_github_tracker.workspace import OWNER, REPO

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Return dt converted to UTC if aware, or set to UTC if naive."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _commit_date(commit_data: dict) -> datetime | None:
    """Extract author/committer date from GitHub commit payload."""
    commit = commit_data.get("commit") or {}
    author = commit.get("author") or commit.get("committer") or {}
    date_str = author.get("date")
    if not date_str:
        return None
    return clang_state.parse_iso(date_str)


def _issue_date(issue_data: dict) -> datetime | None:
    """Extract updated_at or created_at from GitHub issue payload.
    Fetcher yields {issue_info: <detail>, comments: [...]}, so check nested first.
    """
    info = issue_data.get("issue_info") or issue_data
    date_str = info.get("updated_at") or info.get("created_at")
    if not date_str:
        return None
    return clang_state.parse_iso(date_str)


def _pr_date(pr_data: dict) -> datetime | None:
    """Extract updated_at or created_at from GitHub PR payload.
    Fetcher yields {pr_info: <detail>, comments: [...], reviews: [...]}, so check nested first.
    """
    info = pr_data.get("pr_info") or pr_data
    date_str = info.get("updated_at") or info.get("created_at")
    if not date_str:
        return None
    return clang_state.parse_iso(date_str)


def sync_raw_only(
    start_commit: datetime | None = None,
    start_issue: datetime | None = None,
    start_pr: datetime | None = None,
    end_date: Optional[datetime] = None,
) -> tuple[int, list[int], list[int]]:
    """
    Fetch llvm/llvm-project commits, issues, PRs from GitHub and save only to
    raw/github_activity_tracker/llvm/llvm-project. No DB writes.

    Args:
        start_commit: Start date for commits (None = from beginning).
        start_issue: Issue watermark for the unified issues+PRs fetch (one ``/issues``
            list with both item kinds). ``None`` only means “no issue cursor” when
            deriving the shared start: if ``start_pr`` is also ``None``, the unified
            fetch runs from the beginning; if ``start_pr`` is set, that timestamp is
            used as the single lower bound for the whole list (issues are filtered
            by the same window). When both ``start_issue`` and ``start_pr`` are set,
            the shared lower bound is the **later** of the two (``max``), so one
            GitHub query covers both types from that time forward.
        start_pr: PR watermark; same shared-bound semantics as ``start_issue``.
        end_date: End date for all (default: now).

    Returns:
        (commits_saved, issue_numbers, pr_numbers) — commit count and lists of
        issue/PR numbers saved during this run.
    """
    from django.utils import timezone as django_tz

    owner = OWNER
    repo = REPO
    if end_date is None:
        end_date = django_tz.now()
    end_date = _ensure_utc(end_date)
    start_commit = _ensure_utc(start_commit)
    start_issue = _ensure_utc(start_issue)
    start_pr = _ensure_utc(start_pr)

    client = get_github_client(use="scraping")

    commits_saved = 0
    issue_numbers: list[int] = []
    pr_numbers: list[int] = []
    latest_commit: datetime | None = None
    latest_issue: datetime | None = None
    latest_pr: datetime | None = None

    # Single lower bound for the unified /issues fetch: later of the two when both
    # watermarks exist; otherwise whichever side is initialized (or None if both).
    if start_issue and start_pr:
        start_item = max(start_issue, start_pr)
    else:
        start_item = start_issue or start_pr

    try:
        # Commits
        for commit_data in fetcher.fetch_commits_from_github(
            client, owner, repo, start_commit, end_date
        ):
            sha = commit_data.get("sha")
            if sha:
                save_commit_raw_source(owner, repo, commit_data)
                commits_saved += 1
                dt = _commit_date(commit_data)
                if dt and (latest_commit is None or dt > latest_commit):
                    latest_commit = dt
        if latest_commit is not None:
            clang_state.save_state(last_commit_date=latest_commit, merge=True)

        # Issues and PRs — fetched together via a single /issues list call.
        for item in fetcher.fetch_issues_and_prs_from_github(
            client, owner, repo, start_item, end_date
        ):
            if "pr_info" in item:
                pr_number = (item["pr_info"] or {}).get("number")
                if pr_number is not None:
                    save_pr_raw_source(owner, repo, item)
                    pr_numbers.append(pr_number)
                    dt = _pr_date(item)
                    if dt and (latest_pr is None or dt > latest_pr):
                        latest_pr = dt
            else:
                issue_number = (item.get("issue_info") or {}).get("number") or item.get(
                    "number"
                )
                if issue_number is not None:
                    save_issue_raw_source(owner, repo, item)
                    issue_numbers.append(issue_number)
                    dt = _issue_date(item)
                    if dt and (latest_issue is None or dt > latest_issue):
                        latest_issue = dt

        if latest_issue is not None:
            clang_state.save_state(last_issue_date=latest_issue, merge=True)
        if latest_pr is not None:
            clang_state.save_state(last_pr_date=latest_pr, merge=True)

    except (ConnectionException, RateLimitException) as e:
        logger.exception("clang_github_tracker sync failed: %s", e)
        raise

    return commits_saved, issue_numbers, pr_numbers
