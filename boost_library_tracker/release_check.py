"""
Check whether a new Boost release exists (GitHub API vs BoostVersion in DB).
Used by boost_collector_runner when running schedule=on_release tasks.
Only considers stable releases: tag must be boost-X.Y.Z (e.g. boost-1.90.0).
Excludes pre-releases (beta, rc, rc1, etc.). Minimum version: 1.16.1.
"""

import logging
import re

from boost_library_tracker.models import BoostVersion
from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_token

logger = logging.getLogger(__name__)

MAIN_OWNER = "boostorg"
MAIN_REPO = "boost"

# Only boost-X.Y.Z (three numeric parts, no suffix like -beta, -rc, etc.)
BOOST_TAG_PATTERN = re.compile(r"^boost-(\d+)\.(\d+)\.(\d+)$")
MIN_BOOST_VERSION = (1, 16, 1)


def _parse_stable_version(tag_name: str) -> tuple[int, int, int] | None:
    """
    Return (major, minor, patch) if tag is a stable release boost-X.Y.Z and version >= MIN_BOOST_VERSION.
    Return None for pre-releases (boost-1.90.0-beta, rc1, etc.) or versions below minimum.
    """
    if not tag_name:
        return None
    m = BOOST_TAG_PATTERN.match(tag_name.strip())
    if not m:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if (major, minor, patch) < MIN_BOOST_VERSION:
        return None
    return (major, minor, patch)


def has_new_boost_release() -> bool:
    """
    Return True if the GitHub API has at least one tag (from /tags) whose name
    is a stable boost-X.Y.Z (>= 1.16.1) not yet in BoostVersion. Return False
    if all known tags are already in the DB, or on API/network errors.
    Pre-releases (beta, rc, etc.) are ignored. Uses /tags so new tags are
    detected as soon as they are pushed, without waiting for a Release object.
    """
    try:
        token = get_github_token(use="scraping")
    except ValueError as e:
        logger.warning("No GitHub token; cannot check for new Boost release: %s", e)
        return False

    if not token:
        logger.warning("No GitHub token; cannot check for new Boost release")
        return False

    try:
        client = GitHubAPIClient(token)
        existing = set(BoostVersion.objects.values_list("version", flat=True))
        page = 1
        per_page = 100
        while True:
            page_tags = client.rest_request(
                f"/repos/{MAIN_OWNER}/{MAIN_REPO}/tags",
                params={"per_page": per_page, "page": page},
            )
            if not page_tags:
                break
            for r in page_tags:
                tag = r.get("name")
                if not tag or tag in existing:
                    continue
                if _parse_stable_version(tag) is not None:
                    logger.info("New Boost release detected: %s", tag)
                    return True
            if len(page_tags) < per_page:
                break
            page += 1
    except Exception:
        logger.exception("Failed to check for new Boost release")
        return False
    return False
