"""
Date resolution for clang_github_tracker sync windows.

Uses DB watermarks on ClangGithubIssueItem / ClangGithubCommit (not state.json).
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.utils import timezone

from clang_github_tracker.services import (
    get_commit_watermark,
    get_issue_item_watermark,
    start_after_watermark,
)

logger = logging.getLogger(__name__)


def parse_iso(s: str | None) -> datetime | None:
    """Parse ISO datetime string; returns None if missing or invalid."""
    if not s or not isinstance(s, str) or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.utc)
    return dt.astimezone(timezone.utc)


def _apply_since_floor(cursor_start: datetime | None, since: datetime | None) -> datetime | None:
    """Lower bound: max(DB cursor, ``since``) when ``since`` is set; else DB cursor."""
    if since is None:
        return cursor_start
    s = _aware_utc(since)
    if cursor_start is None:
        return s
    c = _aware_utc(cursor_start)
    assert c is not None and s is not None
    return max(c, s)


def resolve_start_end_dates(
    since: datetime | None,
    until: datetime | None,
) -> tuple[datetime | None, datetime | None, datetime]:
    """
    Resolve ``start_commit``, unified ``start_item`` (issues+PRs), and ``end_date``.

    - If both ``since`` and ``until`` are set and ``since <= until``: use ``since`` for
      both starts and ``until`` as end.
    - If ``since > until``: log warning and ignore both bounds (fall back to DB + now).
    - Otherwise: starts from DB max + 1s (or None if empty/null max), with optional
      ``since`` as a per-stream floor. End is ``until`` or ``timezone.now()``.
    """
    since_aware = _aware_utc(since)
    until_aware = _aware_utc(until)

    if since_aware is not None and until_aware is not None:
        if since_aware > until_aware:
            logger.warning(
                "invalid date range: since (%s) is after until (%s); using DB cursors and default end",
                since_aware,
                until_aware,
            )
            since_aware, until_aware = None, None
        else:
            return since_aware, since_aware, until_aware

    end_date = until_aware if until_aware is not None else timezone.now()

    item_wm = start_after_watermark(get_issue_item_watermark())
    commit_wm = start_after_watermark(get_commit_watermark())

    start_item = _apply_since_floor(item_wm, since_aware)
    start_commit = _apply_since_floor(commit_wm, since_aware)

    return start_commit, start_item, end_date
