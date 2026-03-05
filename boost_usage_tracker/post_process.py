"""
Post-processing for boost_usage_tracker batch include search results.

This module handles per-repository persistence only:
- extract Boost headers from fetched file content,
- map headers to BoostFile,
- register BoostUsage rows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from boost_library_tracker.models import BoostFile
from boost_usage_tracker.boost_searcher import (
    detect_boost_version_in_repo,
    extract_boost_includes,
)
from boost_usage_tracker.repo_searcher import RepoSearchResult
from boost_usage_tracker.services import (
    bulk_create_or_update_boost_usage,
    get_active_usages_for_repo,
    get_or_create_boost_external_repo,
    get_or_create_missing_header_usage,
    mark_usages_excepted_bulk,
)
from github_activity_tracker.services import create_or_update_github_file
from github_ops.client import ConnectionException, RateLimitException

if TYPE_CHECKING:
    from github_activity_tracker.models import GitHubRepository

logger = logging.getLogger(__name__)


def _resolve_boost_header(header_path: str):
    """Resolve a Boost include path to a :class:`BoostFile` or *None*."""
    parts = header_path.split("/")
    for i in range(len(parts)):
        suffix = "/".join(parts[i:])
        boost_file = (
            BoostFile.objects.filter(  # pylint: disable=no-member
                github_file__filename__endswith=suffix
            )
            .select_related("github_file")
            .first()
        )  # pylint: disable=no-member
        if boost_file:
            return boost_file
    return None


def _resolve_boost_headers_bulk(header_paths: set[str]) -> dict[str, object]:
    """Resolve a set of Boost include paths to BoostFile instances in one pass.

    Returns a dict ``{header_path: BoostFile | None}``.  Deduplicates the
    incoming paths and performs one bulk exact-match query first; unresolved
    paths are then handled by suffix fallback.
    """
    if not header_paths:
        return {}

    # Fast path: one bulk query for exact filename matches.
    exact_rows = (
        BoostFile.objects.filter(
            github_file__filename__in=header_paths
        )  # pylint: disable=no-member
        .select_related("github_file")
        .order_by("github_file_id")
    )
    by_filename: dict[str, object] = {}
    for row in exact_rows:
        filename = row.github_file.filename
        if filename not in by_filename:
            by_filename[filename] = row

    resolved: dict[str, object] = {}
    unresolved: list[str] = []
    for path in header_paths:
        boost_file = by_filename.get(path)
        if boost_file is not None:
            resolved[path] = boost_file
        else:
            unresolved.append(path)

    # Fallback for non-exact cases (still deduplicated by unique header path).
    for path in unresolved:
        resolved[path] = _resolve_boost_header(path)

    return resolved


def process_single_repo(
    client,
    repo_result: RepoSearchResult,
    file_results_for_repo: list,
    db_last_commit_date: datetime,
    ensure_repo_fn: Callable[[object, RepoSearchResult], "GitHubRepository"],
) -> dict:
    """Persist Boost usage data for one repository from pre-fetched file results.

    The caller provides *file_results_for_repo* from
    ``search_boost_include_files_batch``.
    """
    stats = {
        "usages_created": 0,
        "usages_updated": 0,
        "usages_excepted": 0,
        "missing_header_recorded": 0,
        "boost_used": False,
    }
    repo_full_name = repo_result.full_name

    try:
        github_repo = ensure_repo_fn(client, repo_result)
        is_boost_used = False
        is_embedded = False
        boost_version = ""
        if file_results_for_repo:
            is_embedded, boost_version = detect_boost_version_in_repo(
                client, repo_full_name
            )
            is_boost_used = True

        ext_repo, _ = get_or_create_boost_external_repo(
            github_repo,
            boost_version=boost_version or "",
            is_boost_embedded=is_embedded,
            is_boost_used=is_boost_used,
        )

        if not file_results_for_repo:
            return stats

        stats["boost_used"] = is_boost_used
        existing_usages = get_active_usages_for_repo(ext_repo)
        seen_keys: set[tuple[int | None, int]] = set()
        seen_file_paths: set[int] = set()

        # --- Pass 1: collect file/header data without touching the DB ---
        # This mirrors old process_boost_usage_files which gathered all headers
        # first and then called get_or_set_header_ids_bulk in one shot.
        file_header_map: list[tuple] = []  # (file_result, [header_path, ...])
        all_header_paths: set[str] = set()
        for file_result in file_results_for_repo:
            source_file, created = create_or_update_github_file(
                github_repo, file_result.file_path
            )
            if (
                not created
                and file_result.commit_date
                and file_result.commit_date <= db_last_commit_date
            ):
                seen_file_paths.add(source_file.pk)
                logger.debug(
                    "Skipping file %s in %s: already processed. File ID: %s",
                    file_result.file_path,
                    repo_full_name,
                    source_file.pk,
                )
                continue
            header_paths = extract_boost_includes(file_result.content or "")
            if not header_paths:
                header_paths = list(file_result.boost_headers or [])
            file_header_map.append((source_file, file_result, header_paths))
            all_header_paths.update(header_paths)

        # --- Pass 2: resolve all unique header paths in one bulk call ---
        # Each unique path causes at most one DB query instead of one per occurrence.
        header_cache = _resolve_boost_headers_bulk(all_header_paths)

        # --- Pass 3: persist per-file results using the cached header map ---
        # Collect (boost_header, file_path, last_commit_date) for bulk upsert;
        # handle missing headers in the same loop.
        bulk_usage_items: list[tuple] = []

        for source_file, file_result, header_paths in file_header_map:
            for header_path in header_paths:
                boost_header = header_cache.get(header_path)
                if boost_header is None:
                    _, _, created_tmp = get_or_create_missing_header_usage(
                        repo=ext_repo,
                        file_path=source_file,
                        header_name=header_path,
                        last_commit_date=file_result.commit_date,
                    )
                    if created_tmp:
                        stats["missing_header_recorded"] += 1
                    seen_keys.add((None, source_file.pk))
                    logger.debug(
                        "No BoostFile for header '%s' in %s; recorded in BoostMissingHeaderTmp",
                        header_path,
                        repo_full_name,
                    )
                    continue

                key = (boost_header.pk, source_file.pk)
                seen_keys.add(key)
                bulk_usage_items.append(
                    (boost_header, source_file, file_result.commit_date),
                )

        # Bulk create/update usages (fewer DB round-trips)
        if bulk_usage_items:
            created_count, updated_count = bulk_create_or_update_boost_usage(
                ext_repo, bulk_usage_items
            )
            stats["usages_created"] += created_count
            stats["usages_updated"] += updated_count

        # Bulk mark usages that are no longer detected as excepted
        excepted_ids = [
            u.pk
            for u in existing_usages
            if (u.boost_header_id, u.file_path_id) not in seen_keys
            and u.file_path_id not in seen_file_paths
        ]
        if excepted_ids:
            stats["usages_excepted"] += mark_usages_excepted_bulk(excepted_ids)

    except (ConnectionException, RateLimitException):
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed post-processing %s: %s", repo_full_name, e)

    return stats
