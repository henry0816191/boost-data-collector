"""
Detect stable Boost release tags on GitHub vs ``BoostVersion`` rows in the database.

Used by ``boost_collector_runner`` for ``schedule=on_release`` tasks.

Rules:
- Tag must match ``boost-X.Y.Z`` (three numeric parts only; no ``-beta``, ``-rc``, etc.).
- Minimum version: 1.16.1.

Uses the repository **tags** API so new tags are visible as soon as they are pushed
(without requiring a GitHub ``Release`` object).
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


def _parse_stable_version(tag_name: str) -> str | None:
    """
    If ``tag_name`` is a stable release tag ``boost-X.Y.Z`` with version >= MIN_BOOST_VERSION,
    return the canonical tag string (e.g. ``boost-1.90.0``).

    Return ``None`` for non-matching names, pre-release-style tags, or versions below the minimum.
    """
    if not tag_name:
        return None
    m = BOOST_TAG_PATTERN.match(tag_name.strip())
    if not m:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if (major, minor, patch) < MIN_BOOST_VERSION:
        return None
    return f"boost-{major}.{minor}.{patch}"


def all_boost_versions_from_api() -> list[tuple[str, str]] | None:
    """
    List stable Boost release tags from GitHub (``/repos/boostorg/boost/tags``).

    Returns:
        List of ``(tag_name, commit_sha)`` for each stable tag, newest pages first
        (same order as the API). ``commit_sha`` may be empty if the payload omits it.
        ``None`` if the token is missing or the fetch cannot run (error is logged).
    """
    try:
        token = get_github_token(use="scraping")
    except ValueError as e:
        logger.warning("No GitHub token; cannot fetch Boost tags from API: %s", e)
        return None

    if not token:
        logger.warning("No GitHub token; cannot fetch Boost tags from API")
        return None
    client = GitHubAPIClient(token)
    per_page = 100
    page = 1
    boost_versions: list[tuple[str, str]] = []
    while True:
        page_tags = client.rest_request(
            f"/repos/{MAIN_OWNER}/{MAIN_REPO}/tags",
            params={"per_page": per_page, "page": page},
        )
        if not page_tags:
            break
        for tag in page_tags:
            stable_tag = _parse_stable_version(tag.get("name", ""))
            if not stable_tag:
                continue
            tag_commit = tag.get("commit") or {}
            if not tag_commit:
                continue
            sha = (tag_commit.get("sha") or "").strip()
            boost_versions.append((stable_tag, sha))
        if len(page_tags) < per_page:
            break
        page += 1
    return boost_versions


def has_new_boost_release() -> bool:
    """
    Return True if GitHub has at least one stable ``boost-X.Y.Z`` tag (>= 1.16.1)
    that is not present in ``BoostVersion``.

    Return False if every such tag already exists in the database, if no stable tags
    were returned, or if the API could not be queried (errors logged elsewhere).
    """
    boost_versions = all_boost_versions_from_api()
    if boost_versions is None:
        return False
    if not boost_versions:
        logger.warning("No stable Boost tags found from API")
        return False
    existing_versions = set(BoostVersion.objects.values_list("version", flat=True))
    return any(version not in existing_versions for version, _sha in boost_versions)


def new_boost_versions_from_api() -> list[tuple[str, str]]:
    """
    Return stable ``(tag_name, commit_sha)`` pairs from GitHub that are not yet in ``BoostVersion``.

    Same filtering as :func:`has_new_boost_release`, but returns the full list of new pairs.
    On API/token failure, returns an empty list (failure is logged by
    :func:`all_boost_versions_from_api`).
    """
    boost_versions = all_boost_versions_from_api()
    if boost_versions is None:
        return []
    if not boost_versions:
        logger.warning("No stable Boost tags found from API")
        return []
    existing_versions = set(BoostVersion.objects.values_list("version", flat=True))
    return [pair for pair in boost_versions if pair[0] not in existing_versions]
