"""DB upsert and watermark helpers for clang_github_tracker."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Max
from django.utils import timezone

from clang_github_tracker.models import ClangGithubCommit, ClangGithubIssueItem

logger = logging.getLogger(__name__)

DEFAULT_UPSERT_BATCH_SIZE = 500


def upsert_issue_item(
    number: int,
    *,
    is_pull_request: bool,
    github_created_at: datetime | None,
    github_updated_at: datetime | None,
) -> tuple[ClangGithubIssueItem, bool]:
    """Create or update a ClangGithubIssueItem by ``number``. Returns (instance, created)."""
    obj, created = ClangGithubIssueItem.objects.update_or_create(
        number=number,
        defaults={
            "is_pull_request": is_pull_request,
            "github_created_at": github_created_at,
            "github_updated_at": github_updated_at,
        },
    )
    logger.debug(
        "clang issue item #%s %s (pr=%s)",
        number,
        "created" if created else "updated",
        is_pull_request,
    )
    return obj, created


def upsert_commit(
    sha: str,
    *,
    github_committed_at: datetime | None,
) -> tuple[ClangGithubCommit, bool]:
    """Create or update a ClangGithubCommit by ``sha``. Returns (instance, created)."""
    sha_clean = (sha or "").strip()
    if len(sha_clean) != 40:
        raise ValueError(f"commit sha must be 40 hex chars, got {sha_clean!r}")
    obj, created = ClangGithubCommit.objects.update_or_create(
        sha=sha_clean,
        defaults={"github_committed_at": github_committed_at},
    )
    logger.debug(
        "clang commit %s %s",
        sha_clean[:8],
        "created" if created else "updated",
    )
    return obj, created


def _flush_commits_chunk(
    pairs: list[tuple[str, datetime | None]],
) -> tuple[int, int]:
    """Write one chunk; returns (inserted_count, updated_count)."""
    if not pairs:
        return 0, 0
    shas = [s for s, _ in pairs]
    existing = set(
        ClangGithubCommit.objects.filter(sha__in=shas).values_list("sha", flat=True)
    )
    now = timezone.now()
    objs = [
        ClangGithubCommit(sha=s, github_committed_at=dt, updated_at=now)
        for s, dt in pairs
    ]
    ClangGithubCommit.objects.bulk_create(
        objs,
        batch_size=len(objs),
        update_conflicts=True,
        unique_fields=["sha"],
        update_fields=["github_committed_at", "updated_at"],
    )
    inserted = sum(1 for s, _ in pairs if s not in existing)
    updated = len(pairs) - inserted
    return inserted, updated


def upsert_commits_batch(
    rows: Sequence[tuple[str, datetime | None]],
    *,
    batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
) -> tuple[int, int]:
    """Batch upsert commits by ``sha``. Skips rows whose sha is not 40 chars.

    Returns:
        (inserted, updated) counts across all batches.
    """
    merged: dict[str, datetime | None] = {}
    for sha, dt in rows:
        s = (sha or "").strip()
        if len(s) != 40:
            continue
        merged[s] = dt
    inserted = updated = 0
    items = list(merged.items())
    for i in range(0, len(items), batch_size):
        di, du = _flush_commits_chunk(items[i : i + batch_size])
        inserted += di
        updated += du
    return inserted, updated


def _flush_issue_items_chunk(
    rows: list[tuple[int, bool, datetime | None, datetime | None]],
) -> tuple[int, int]:
    """Bulk upsert one chunk of issue/PR rows; returns (inserted, updated)."""
    if not rows:
        return 0, 0
    nums = [n for n, _, _, _ in rows]
    existing = set(
        ClangGithubIssueItem.objects.filter(number__in=nums).values_list(
            "number", flat=True
        )
    )
    now = timezone.now()
    objs = [
        ClangGithubIssueItem(
            number=n,
            is_pull_request=is_pr,
            github_created_at=gc,
            github_updated_at=gu,
            updated_at=now,
        )
        for n, is_pr, gc, gu in rows
    ]
    ClangGithubIssueItem.objects.bulk_create(
        objs,
        batch_size=len(objs),
        update_conflicts=True,
        unique_fields=["number"],
        update_fields=[
            "is_pull_request",
            "github_created_at",
            "github_updated_at",
            "updated_at",
        ],
    )
    inserted = sum(1 for n, _, _, _ in rows if n not in existing)
    updated = len(rows) - inserted
    return inserted, updated


def upsert_issue_items_batch(
    rows: Sequence[tuple[int, bool, datetime | None, datetime | None]],
    *,
    batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
) -> tuple[int, int]:
    """Batch upsert issue/PR rows by ``number``. Later rows win on duplicate numbers.

    Returns:
        (inserted, updated) counts across all batches.
    """
    merged: dict[int, tuple[bool, datetime | None, datetime | None]] = {}
    for num, is_pr, gc, gu in rows:
        if not isinstance(num, int) or num <= 0:
            continue
        merged[num] = (is_pr, gc, gu)
    inserted = updated = 0
    items = [(n, is_pr, gc, gu) for n, (is_pr, gc, gu) in sorted(merged.items())]
    for i in range(0, len(items), batch_size):
        di, du = _flush_issue_items_chunk(items[i : i + batch_size])
        inserted += di
        updated += du
    return inserted, updated


def get_issue_item_watermark() -> Optional[datetime]:
    """Max ``github_updated_at`` across issues and PRs (API fetch cursor base)."""
    m = ClangGithubIssueItem.objects.aggregate(m=Max("github_updated_at"))["m"]
    return m


def get_commit_watermark() -> Optional[datetime]:
    """Max ``github_committed_at`` across commits (API fetch cursor base)."""
    m = ClangGithubCommit.objects.aggregate(m=Max("github_committed_at"))["m"]
    return m


def start_after_watermark(max_dt: datetime | None) -> datetime | None:
    """Return ``max + 1ms`` for API fetch lower bound, or ``None`` if no watermark."""
    if max_dt is None:
        return None
    return max_dt + timedelta(milliseconds=1)
