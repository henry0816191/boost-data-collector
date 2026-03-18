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
    """Extract updated_at or created_at from GitHub issue payload."""
    date_str = issue_data.get("updated_at") or issue_data.get("created_at")
    if not date_str:
        return None
    return clang_state.parse_iso(date_str)


def _pr_date(pr_data: dict) -> datetime | None:
    """Extract updated_at or created_at from GitHub PR payload."""
    date_str = pr_data.get("updated_at") or pr_data.get("created_at")
    if not date_str:
        return None
    return clang_state.parse_iso(date_str)


def sync_raw_only(
    start_commit: datetime | None = None,
    start_issue: datetime | None = None,
    start_pr: datetime | None = None,
    end_date: Optional[datetime] = None,
) -> tuple[int, int, int]:
    """
    Fetch llvm/llvm-project commits, issues, PRs from GitHub and save only to
    raw/github_activity_tracker/llvm/llvm-project. No DB writes.

    Args:
        start_commit: Start date for commits (None = from beginning).
        start_issue: Start date for issues (None = from beginning).
        start_pr: Start date for PRs (None = from beginning).
        end_date: End date for all (default: now).

    Returns:
        (commits_saved, issues_saved, prs_saved).
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
    issues_saved = 0
    prs_saved = 0
    latest_commit: datetime | None = None
    latest_issue: datetime | None = None
    latest_pr: datetime | None = None

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

        # Issues
        for issue_data in fetcher.fetch_issues_from_github(
            client, owner, repo, start_issue, end_date
        ):
            issue_number = issue_data.get("number") or (
                issue_data.get("issue_info") or {}
            ).get("number")
            if issue_number is not None:
                save_issue_raw_source(owner, repo, issue_data)
                issues_saved += 1
                dt = _issue_date(issue_data)
                if dt and (latest_issue is None or dt > latest_issue):
                    latest_issue = dt
        if latest_issue is not None:
            clang_state.save_state(last_issue_date=latest_issue, merge=True)

        # PRs
        for pr_data in fetcher.fetch_pull_requests_from_github(
            client, owner, repo, start_pr, end_date
        ):
            pr_number = (pr_data.get("pr_info") or {}).get("number") or pr_data.get(
                "number"
            )
            if pr_number is not None:
                save_pr_raw_source(owner, repo, pr_data)
                prs_saved += 1
                dt = _pr_date(pr_data)
                if dt and (latest_pr is None or dt > latest_pr):
                    latest_pr = dt
        if latest_pr is not None:
            clang_state.save_state(last_pr_date=latest_pr, merge=True)

    except (ConnectionException, RateLimitException) as e:
        logger.exception("clang_github_tracker sync failed: %s", e)
        raise

    return commits_saved, issues_saved, prs_saved
