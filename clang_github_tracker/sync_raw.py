"""
Sync llvm/llvm-project to raw/github_activity_tracker and clang_github_tracker DB.

Uses github_activity_tracker.fetcher and raw_source; persists issue/PR/commit rows via services.
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
from github_activity_tracker.sync.utils import (
    normalize_issue_json,
    normalize_pr_json,
    parse_datetime,
)
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException

from clang_github_tracker import state_manager as clang_state
from clang_github_tracker import services as clang_services
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
    return parse_datetime(date_str) or clang_state.parse_iso(date_str)


def sync_raw_only(
    start_commit: datetime | None = None,
    start_item: datetime | None = None,
    end_date: Optional[datetime] = None,
) -> tuple[int, list[int], list[int]]:
    """
    Fetch llvm/llvm-project commits, issues, PRs from GitHub and save to raw paths
    and upsert ``ClangGithubCommit`` / ``ClangGithubIssueItem``.

    Args:
        start_commit: Start date for commits (None = from beginning).
        start_item: Single lower bound for unified issues+PRs ``/issues`` fetch.
        end_date: End date for all (default: now).

    Returns:
        (commits_saved, issue_numbers, pr_numbers).
    """
    from django.utils import timezone as django_tz

    owner = OWNER
    repo = REPO
    if end_date is None:
        end_date = django_tz.now()
    end_date = _ensure_utc(end_date)
    start_commit = _ensure_utc(start_commit)
    start_item = _ensure_utc(start_item)

    client = get_github_client(use="scraping")

    commits_saved = 0
    issue_numbers: list[int] = []
    pr_numbers: list[int] = []

    try:
        for commit_data in fetcher.fetch_commits_from_github(
            client, owner, repo, start_commit, end_date
        ):
            sha = commit_data.get("sha")
            if sha:
                save_commit_raw_source(owner, repo, commit_data)
                commits_saved += 1
                committed_at = _commit_date(commit_data)
                try:
                    clang_services.upsert_commit(
                        str(sha).strip(),
                        github_committed_at=committed_at,
                    )
                except ValueError as e:
                    logger.warning("skip commit DB upsert: %s", e)

        for item in fetcher.fetch_issues_and_prs_from_github(
            client, owner, repo, start_item, end_date
        ):
            if "pr_info" in item:
                pr_number = (item["pr_info"] or {}).get("number")
                if pr_number is not None:
                    save_pr_raw_source(owner, repo, item)
                    pr_numbers.append(pr_number)
                    flat = normalize_pr_json(item)
                    num = flat.get("number")
                    if isinstance(num, int) and num > 0:
                        clang_services.upsert_issue_item(
                            num,
                            is_pull_request=True,
                            github_created_at=parse_datetime(flat.get("created_at")),
                            github_updated_at=parse_datetime(flat.get("updated_at")),
                        )
            else:
                issue_number = (item.get("issue_info") or {}).get("number") or item.get(
                    "number"
                )
                if issue_number is not None:
                    save_issue_raw_source(owner, repo, item)
                    issue_numbers.append(issue_number)
                    flat = normalize_issue_json(item)
                    num = flat.get("number")
                    if isinstance(num, int) and num > 0:
                        clang_services.upsert_issue_item(
                            num,
                            is_pull_request=False,
                            github_created_at=parse_datetime(flat.get("created_at")),
                            github_updated_at=parse_datetime(flat.get("updated_at")),
                        )

    except (ConnectionException, RateLimitException) as e:
        logger.exception("clang_github_tracker sync failed: %s", e)
        raise

    return commits_saved, issue_numbers, pr_numbers
