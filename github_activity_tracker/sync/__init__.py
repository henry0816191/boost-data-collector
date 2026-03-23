"""
GitHub sync package: read last updated from DB, fetch from GitHub, save via services.

Split by entity: repos, commits, issues, pull_requests.
Entry point: sync_github(repo) runs all in order for that repo.
Accepts GitHubRepository or any subclass (e.g. BoostLibraryRepository); base fields are used.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .commits import sync_commits
from .issues import sync_issues
from .pull_requests import sync_pull_requests
from .repos import sync_repos

if TYPE_CHECKING:
    from ..models import GitHubRepository


def sync_github(
    repo: GitHubRepository,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict[str, list[int]]:
    """Run full sync for one repo: repos (metadata), then commits, issues, pull requests.

    Accepts GitHubRepository or a subclass (e.g. BoostLibraryRepository); the same
    base row is used, so extended models can be passed and sync will work.

    Args:
        repo: Repository to sync.
        start_date: Override start date for commits/issues/PRs (default: auto from DB).
        end_date: Override end date for commits/issues/PRs (default: now).

    Returns:
        Dict with "issues" and "pull_requests" keys, each a list of numbers processed
        during this sync run.
    """
    sync_repos(repo)
    sync_commits(repo, start_date=start_date, end_date=end_date)
    issue_numbers = sync_issues(repo, start_date=start_date, end_date=end_date)
    pr_numbers = sync_pull_requests(repo, start_date=start_date, end_date=end_date)
    return {"issues": issue_numbers, "pull_requests": pr_numbers}
