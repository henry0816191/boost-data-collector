"""DB upsert and watermark helpers for clang_github_tracker."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Max

from clang_github_tracker.models import ClangGithubCommit, ClangGithubIssueItem

logger = logging.getLogger(__name__)


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
