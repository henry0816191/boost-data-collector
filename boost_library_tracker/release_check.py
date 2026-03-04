"""
Check whether a new Boost release exists (GitHub API vs BoostVersion in DB).
Used by boost_collector_runner when running schedule=on_release tasks.
"""

import logging

from boost_library_tracker.models import BoostVersion
from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_token

logger = logging.getLogger(__name__)

MAIN_OWNER = "boostorg"
MAIN_REPO = "boost"


def has_new_boost_release() -> bool:
    """
    Return True if the GitHub API has at least one release whose tag_name
    is not yet in BoostVersion. Return False if all known releases are
    already in the DB, or on API/network errors (no new release assumed).
    """
    token = get_github_token()
    if not token:
        logger.warning("No GitHub token; cannot check for new Boost release")
        return False
    client = GitHubAPIClient(token)
    existing = set(BoostVersion.objects.values_list("version", flat=True))
    page = 1
    per_page = 100
    try:
        while True:
            page_releases = client.rest_request(
                f"/repos/{MAIN_OWNER}/{MAIN_REPO}/releases",
                params={"per_page": per_page, "page": page},
            )
            if not page_releases:
                break
            for r in page_releases:
                tag = r.get("tag_name")
                if tag and tag not in existing:
                    logger.info("New Boost release detected: %s", tag)
                    return True
            if len(page_releases) < per_page:
                break
            page += 1
    except Exception as e:
        logger.warning("Failed to check for new Boost release: %s", e)
        return False
    return False
