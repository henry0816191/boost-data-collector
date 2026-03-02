"""
Count yearly created repositories by language via GitHub REST API and upsert DB rows.

Target table:
  github_activity_tracker_createdreposbylanguage
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from github_activity_tracker.models import Language
from github_activity_tracker.services import create_or_update_created_repos_by_language
from github_ops import get_github_client
from github_ops.client import ConnectionException, GitHubAPIClient, RateLimitException

logger = logging.getLogger(__name__)

LANGUAGES_ENV_KEY = "REPO_COUNT_LANGUAGES"


def _parse_languages_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _count_items_from_git(client: GitHubAPIClient, query: str) -> int:
    data = client.rest_request(
        "/search/repositories",
        params={"q": query, "per_page": 1},
    )
    return int(data.get("total_count", 0))


def update_created_repos_by_language(
    *,
    languages_csv: str | None = None,
    start_year: int = 2010,
    end_year: int | None = None,
    stars_min: int = 10,
    sleep_seconds: float = 0.0,
    fail_on_missing_language: bool = False,
) -> dict[str, Any]:
    """
    Count repositories by language/year and upsert CreatedReposByLanguage rows.

    Languages source:
    - ``languages_csv`` argument, or
    - ``REPO_COUNT_LANGUAGES`` from env (comma-separated).
    """
    if end_year is None:
        end_year = datetime.now(timezone.utc).year
    if start_year > end_year:
        return {
            "created": 0,
            "updated": 0,
            "rows_processed": 0,
            "errors": [
                f"Invalid year range: start_year({start_year}) > end_year({end_year})"
            ],
        }

    source_csv = (languages_csv or os.getenv(LANGUAGES_ENV_KEY, "")).strip()
    language_names = _parse_languages_csv(source_csv)
    if not language_names:
        return {
            "created": 0,
            "updated": 0,
            "rows_processed": 0,
            "errors": [
                f"No languages provided. Set {LANGUAGES_ENV_KEY} in .env or pass --languages.",
            ],
        }

    # Keep input order and uniqueness.
    seen: set[str] = set()
    ordered_language_names: list[str] = []
    for name in language_names:
        if name not in seen:
            seen.add(name)
            ordered_language_names.append(name)

    language_map = {
        lang.name: lang
        for lang in Language.objects.filter(  # pylint: disable=no-member
            name__in=ordered_language_names
        )
    }
    missing = [name for name in ordered_language_names if name not in language_map]
    if missing and fail_on_missing_language:
        result = _result_template(
            start_year=start_year, end_year=end_year, stars_min=stars_min
        )
        result["errors"].append(
            f"Languages not found in Language table: {', '.join(missing)}"
        )
        return result
    if missing:
        logger.warning(
            "Skipping languages not found in Language table: %s", ", ".join(missing)
        )

    created_count = 0
    updated_count = 0
    rows_processed = 0
    errors: list[str] = []
    processed_languages: list[str] = []
    client = get_github_client(use="scraping")

    for language_name in ordered_language_names:
        language_obj = language_map.get(language_name)
        if language_obj is None:
            continue
        processed_languages.append(language_name)

        for year in range(start_year, end_year + 1):
            q_all = f"language:{language_name} created:{year}-01-01..{year}-12-31"
            q_sig = f"language:{language_name} created:{year}-01-01..{year}-12-31 stars:>{stars_min}"
            try:
                all_repos = _count_items_from_git(client, q_all)
                significant_repos = _count_items_from_git(client, q_sig)
                _, created = create_or_update_created_repos_by_language(
                    language=language_obj,
                    year=year,
                    all_repos=all_repos,
                    significant_repos=significant_repos,
                )
                rows_processed += 1
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            except (RateLimitException, ConnectionException):
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                msg = f"Failed for language={language_name}, year={year}: {exc}"
                logger.exception(msg)
                errors.append(msg)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    result = _result_template(
        start_year=start_year, end_year=end_year, stars_min=stars_min
    )
    result["languages_requested"].extend(ordered_language_names)
    result["languages_processed"].extend(processed_languages)
    result["languages_missing"].extend(missing)
    result["created"] += created_count
    result["updated"] += updated_count
    result["rows_processed"] += rows_processed
    result["errors"].extend(errors)
    return result


def _result_template(
    *, start_year: int, end_year: int | None, stars_min: int
) -> dict[str, Any]:
    return {
        "languages_requested": [],
        "languages_processed": [],
        "languages_missing": [],
        "start_year": start_year,
        "end_year": end_year,
        "stars_min": stars_min,
        "created": 0,
        "updated": 0,
        "rows_processed": 0,
        "errors": [],
    }
