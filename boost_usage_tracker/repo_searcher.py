"""
Repository search utilities for boost_usage_tracker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from github_ops.client import GitHubAPIClient

logger = logging.getLogger(__name__)

# Default second date range when splitting "created" (GitHub API limit)
CREATION_START_DEFAULT = datetime(2018, 4, 1, tzinfo=timezone.utc)
CREATION_INTERVAL_DAYS = 360  # chunk size for "created" range generation

PER_PAGE = 100


@dataclass
class RepoSearchResult:
    """Minimal metadata returned by a GitHub repository search."""

    full_name: str  # "owner/repo"
    stars: int = 0
    description: str = ""
    license_spdx: str = ""
    created_at: str = ""
    updated_at: str = ""
    pushed_at: str = ""
    forks: int = 0


def _extract_repo_metadata(item: dict[str, Any]) -> RepoSearchResult:
    license_spdx = ""
    lic = item.get("license")
    if isinstance(lic, dict):
        license_spdx = lic.get("spdx_id") or lic.get("key") or lic.get("name") or ""
    return RepoSearchResult(
        full_name=item.get("full_name") or "",
        stars=item.get("stargazers_count") or 0,
        description=item.get("description") or "",
        license_spdx=license_spdx,
        created_at=item.get("created_at") or "",
        updated_at=item.get("updated_at") or "",
        pushed_at=item.get("pushed_at") or "",
        forks=item.get("forks_count") or 0,
    )


def _search_repos_by_query(
    client: GitHubAPIClient,
    query: str,
) -> list[RepoSearchResult]:
    """Search GitHub repositories with *query* (paginated, up to 1 000 results)."""
    repos: list[RepoSearchResult] = []
    page = 1

    while True:
        try:
            data = client.rest_request(
                "/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": PER_PAGE,
                    "page": page,
                },
            )
        except Exception as e:
            logger.warning("Repo search failed (page %d): %s", page, e)
            break

        items = data.get("items") or []
        if not items:
            break

        for item in items:
            meta = _extract_repo_metadata(item)
            if meta.full_name:
                repos.append(meta)

        if len(items) < PER_PAGE or page >= 10:
            break
        page += 1

    return repos


def generate_date_ranges(
    start_date: datetime,
    end_date: datetime,
    date_field: str = "pushed",
) -> list[tuple[datetime, datetime]]:
    """Generate bounded date ranges for repository search.

    - For ``date_field="pushed"``: one-day ranges.
    - For ``date_field="created"``: ``CREATION_INTERVAL_DAYS``-day chunks.
    """
    data_interval = 0 if date_field == "pushed" else CREATION_INTERVAL_DAYS
    ranges: list[tuple[datetime, datetime]] = []
    current_start = start_date
    while current_start <= end_date:
        next_date = current_start + timedelta(days=data_interval)
        if next_date > end_date:
            next_date = end_date
        ranges.append((current_start, next_date))
        current_start = next_date + timedelta(days=1)
    return ranges


def _process_date_range(
    client: GitHubAPIClient,
    first_range: tuple[datetime, datetime],
    second_range: Optional[tuple[datetime, datetime]] = None,
    date_field: str = "pushed",
    language: str = "C++",
    min_stars: int = 10,
) -> list[RepoSearchResult]:
    """Process a single date range; recursively split when total_count > 1000."""
    primary_str = (
        f"{first_range[0].strftime('%Y-%m-%d')}..{first_range[1].strftime('%Y-%m-%d')}"
    )
    query = f"language:{language} stars:>{min_stars} {date_field}:{primary_str}"
    if second_range:
        query += (
            f" created:{second_range[0].strftime('%Y-%m-%d')}"
            f"..{second_range[1].strftime('%Y-%m-%d')}"
        )

    # time.sleep(SEARCH_DELAY)
    try:
        probe = client.rest_request(
            "/search/repositories",
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": 1,
                "page": 1,
            },
        )
    except Exception as e:
        logger.warning("Date-range count probe failed: %s", e)
        return []

    total_count = probe.get("total_count", 0)
    logger.info("  %s %s: %d repos", date_field, primary_str, total_count)

    if total_count > 1000:
        first_range_1 = first_range
        first_range_2 = first_range
        second_range_1 = second_range
        second_range_2 = second_range
        days_diff = (first_range[1] - first_range[0]).days
        second_diff = 0
        if days_diff > 0:
            mid_date = first_range[0] + timedelta(days=days_diff // 2)
            first_range_1 = (first_range[0], mid_date)
            first_range_2 = (mid_date + timedelta(days=1), first_range[1])
        else:
            if not second_range:
                second_range = (CREATION_START_DEFAULT, datetime.now(timezone.utc))
            second_diff = (second_range[1] - second_range[0]).days
            if second_diff > 0:
                second_mid = second_range[0] + timedelta(days=second_diff // 2)
                second_range_1 = (second_range[0], second_mid)
                second_range_2 = (second_mid + timedelta(days=1), second_range[1])

        if days_diff > 0 or second_diff > 0:
            repos1 = _process_date_range(
                client=client,
                first_range=first_range_1,
                date_field=date_field,
                language=language,
                min_stars=min_stars,
                second_range=second_range_1,
            )
            repos2 = _process_date_range(
                client=client,
                first_range=first_range_2,
                date_field=date_field,
                language=language,
                min_stars=min_stars,
                second_range=second_range_2,
            )
            seen = {r.full_name for r in repos1}
            for r in repos2:
                if r.full_name not in seen:
                    repos1.append(r)
                    seen.add(r.full_name)
            return repos1

        logger.warning(
            "Cannot split further (range %s); returning first 1000",
            primary_str,
        )
        return _search_repos_by_query(client, query)

    return _search_repos_by_query(client, query)


def search_repos_with_date_splitting(
    client: GitHubAPIClient,
    start_date: datetime,
    end_date: datetime,
    date_field: str = "pushed",
    language: str = "C++",
    min_stars: int = 10,
    second_created_range: Optional[tuple[datetime, datetime]] = None,
) -> list[RepoSearchResult]:
    """Search repositories across date range(s), recursively splitting >1000 results."""
    ranges = generate_date_ranges(start_date, end_date, date_field)
    logger.info("Searching across %d time range(s)...", len(ranges))
    total_repos: list[RepoSearchResult] = []
    for idx, (range_start, range_end) in enumerate(ranges, 1):
        logger.info(
            "[%d/%d] Range: %s .. %s",
            idx,
            len(ranges),
            range_start.strftime("%Y-%m-%d"),
            range_end.strftime("%Y-%m-%d"),
        )
        chunk = _process_date_range(
            client,
            first_range=(range_start, range_end),
            date_field=date_field,
            language=language,
            min_stars=min_stars,
            second_range=second_created_range,
        )
        total_repos.extend(chunk)

    seen: set[str] = set()
    unique: list[RepoSearchResult] = []
    for r in total_repos:
        if r.full_name not in seen:
            seen.add(r.full_name)
            unique.append(r)
    return unique
