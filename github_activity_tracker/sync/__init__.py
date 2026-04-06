"""
GitHub sync package: read last updated from DB, fetch from GitHub, save via services.

Split by entity: repos, commits, issues_and_prs.
Entry point: sync_github(repo) runs all in order for that repo.
Accepts GitHubRepository or any subclass (e.g. BoostLibraryRepository); base fields are used.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .commits import sync_commits
from .issues_and_prs import sync_issues_and_prs
from .repos import sync_repos

if TYPE_CHECKING:
    from ..models import GitHubRepository


def sync_github(
    repo: GitHubRepository,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict[str, list[int]]:
    """Run full sync for one repo: repos (metadata), then commits, issues and pull requests.

    Issues and PRs are fetched together via a single GitHub /issues list call which
    returns both; items are routed internally by the presence of a "pull_request" key.

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
    return sync_issues_and_prs(repo, start_date=start_date, end_date=end_date)
