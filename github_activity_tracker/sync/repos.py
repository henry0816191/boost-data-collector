"""
Sync GitHub repositories (and languages, licenses) with the database.
Read last updated from DB, fetch from GitHub, save via github_activity_tracker.services
and cppa_user_tracker.services as needed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException
from github_activity_tracker.sync.utils import parse_datetime

if TYPE_CHECKING:
    from github_activity_tracker.models import GitHubRepository

logger = logging.getLogger(__name__)


def sync_repos(repo: GitHubRepository) -> None:
    """Sync this repo's metadata (and repo languages, repo licenses) from GitHub to the database."""
    logger.info(f"sync_repos: starting for repo id={repo.pk} ({repo.repo_name})")

    try:
        client = get_github_client()

        owner = repo.owner_account.username
        repo_name = repo.repo_name

        # Fetch repo metadata from GitHub
        repo_data = client.get_repository_info(owner, repo_name)

        # Update repo fields (stars, forks, description, dates)
        repo.stars = repo_data.get("stargazers_count", 0)
        repo.forks = repo_data.get("forks_count", 0)
        repo.description = repo_data.get("description") or ""
        repo.repo_pushed_at = parse_datetime(repo_data.get("pushed_at"))
        repo.repo_created_at = parse_datetime(repo_data.get("created_at"))
        repo.repo_updated_at = parse_datetime(repo_data.get("updated_at"))
        repo.save()

        logger.debug(f"Repo {repo_name}: metadata updated")

        # Optionally: fetch and update languages, licenses
        # For languages: GET /repos/{owner}/{repo}/languages returns {"Python": 12345, "C++": 6789, ...}
        # For licenses: repo_data["license"] has {"key": "mit", "name": "MIT License", ...}
        # We could add that logic here or in a separate helper if needed.

        logger.info(f"sync_repos: finished for repo id={repo.pk}")

    except (RateLimitException, ConnectionException) as e:
        logger.error(f"sync_repos: failed for repo id={repo.pk}: {e}")
        raise
    except Exception as e:
        logger.exception(f"sync_repos: unexpected error for repo id={repo.pk}: {e}")
        raise
