"""DB upsert and watermark helpers for clang_github_tracker."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Max
from django.utils import timezone

from clang_github_tracker.models import ClangGithubCommit, ClangGithubIssueItem
from core.utils.datetime_parsing import ensure_aware_utc

logger = logging.getLogger(__name__)

DEFAULT_UPSERT_BATCH_SIZE = 500


def _invalid_issue_number(n: object) -> bool:
    """True if ``n`` is not a positive ``int`` (rejects ``bool`` — it subclasses ``int``)."""
    return isinstance(n, bool) or not isinstance(n, int) or n <= 0


def _max_dt(current: datetime | None, incoming: datetime | None) -> datetime | None:
    """Return the later of two datetimes; ``None`` is treated as missing (never wins over a value)."""
    if current is None:
        return incoming
    if incoming is None:
        return current
    return max(current, incoming)


def _merge_issue_item_fields(
    existing: ClangGithubIssueItem | None,
    is_pull_request: bool,
    github_created_at: datetime | None,
    github_updated_at: datetime | None,
) -> tuple[bool, datetime | None, datetime | None]:
    """Merge incoming issue/PR fields with a stored row (None / older incoming must not weaken state)."""
    if existing is None:
        return (is_pull_request, github_created_at, github_updated_at)
    return (
        existing.is_pull_request or is_pull_request,
        (
            github_created_at
            if github_created_at is not None
            else existing.github_created_at
        ),
        _max_dt(existing.github_updated_at, github_updated_at),
    )


def upsert_issue_item(
    number: int,
    *,
    is_pull_request: bool,
    github_created_at: datetime | None,
    github_updated_at: datetime | None,
) -> tuple[ClangGithubIssueItem, bool]:
    """Create or update a ClangGithubIssueItem by ``number``. Returns (instance, created)."""
    if _invalid_issue_number(number):
        raise ValueError(f"issue number must be a positive integer, got {number!r}")
    github_created_at = ensure_aware_utc(github_created_at)
    github_updated_at = ensure_aware_utc(github_updated_at)
    existing = ClangGithubIssueItem.objects.filter(number=number).first()
    is_pr, gc, gu = _merge_issue_item_fields(
        existing,
        is_pull_request,
        github_created_at,
        github_updated_at,
    )
    obj, created = ClangGithubIssueItem.objects.update_or_create(
        number=number,
        defaults={
            "is_pull_request": is_pr,
            "github_created_at": gc,
            "github_updated_at": gu,
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
    sha_clean = (sha or "").strip().lower()
    if len(sha_clean) != 40:
        raise ValueError(f"commit sha must be 40 hex chars, got {sha_clean!r}")
    github_committed_at = ensure_aware_utc(github_committed_at)
    existing = ClangGithubCommit.objects.filter(sha=sha_clean).first()
    merged_committed_at = _max_dt(
        existing.github_committed_at if existing else None,
        github_committed_at,
    )
    obj, created = ClangGithubCommit.objects.update_or_create(
        sha=sha_clean,
        defaults={"github_committed_at": merged_committed_at},
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
    existing_committed = {
        row.sha: row.github_committed_at
        for row in ClangGithubCommit.objects.filter(sha__in=shas).only(
            "sha", "github_committed_at"
        )
    }
    existing = set(existing_committed.keys())
    now = timezone.now()
    objs = [
        ClangGithubCommit(
            sha=s,
            github_committed_at=_max_dt(
                ensure_aware_utc(existing_committed.get(s)),
                ensure_aware_utc(dt),
            ),
            updated_at=now,
        )
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
    if batch_size <= 0:
        logger.warning(
            "batch_size must be positive, using %s", DEFAULT_UPSERT_BATCH_SIZE
        )
        batch_size = DEFAULT_UPSERT_BATCH_SIZE
    if batch_size > len(rows):
        logger.warning(
            "batch_size is greater than the number of rows, using %s",
            len(rows),
        )
        batch_size = len(rows)
    merged: dict[str, datetime | None] = {}
    for sha, dt in rows:
        s = (sha or "").strip().lower()
        if len(s) != 40:
            continue
        dt_a = ensure_aware_utc(dt)
        merged[s] = _max_dt(merged.get(s), dt_a)
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
    existing_by_num = {
        obj.number: obj
        for obj in ClangGithubIssueItem.objects.filter(number__in=nums).only(
            "number",
            "is_pull_request",
            "github_created_at",
            "github_updated_at",
        )
    }
    existing = set(existing_by_num.keys())
    now = timezone.now()
    objs = []
    for n, is_pr, gc, gu in rows:
        gc = ensure_aware_utc(gc)
        gu = ensure_aware_utc(gu)
        m_is_pr, m_gc, m_gu = _merge_issue_item_fields(
            existing_by_num.get(n), is_pr, gc, gu
        )
        objs.append(
            ClangGithubIssueItem(
                number=n,
                is_pull_request=m_is_pr,
                github_created_at=m_gc,
                github_updated_at=m_gu,
                updated_at=now,
            )
        )
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
    """Batch upsert issue/PR rows by ``number``.

    Duplicate ``number`` values merge: ``github_updated_at`` uses the latest
    timestamp; ``github_created_at`` uses a later row's value when non-None,
    otherwise keeps the prior value; ``is_pull_request`` is True if any row
    marks the number as a PR.

    Returns:
        (inserted, updated) counts across all batches.
    """
    merged: dict[int, tuple[bool, datetime | None, datetime | None]] = {}
    for num, is_pr, gc, gu in rows:
        if _invalid_issue_number(num):
            continue
        gc = ensure_aware_utc(gc)
        gu = ensure_aware_utc(gu)
        prev = merged.get(num)
        if prev is None:
            merged[num] = (is_pr, gc, gu)
        else:
            prev_is_pr, prev_gc, prev_gu = prev
            merged[num] = (
                prev_is_pr or is_pr,
                gc if gc is not None else prev_gc,
                _max_dt(prev_gu, gu),
            )
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
