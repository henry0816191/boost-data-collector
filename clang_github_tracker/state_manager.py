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


def _aware_utc(dt: datetime | None) -> datetime | None:
    """Normalize ``dt`` to timezone-aware UTC, or return ``None``."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_start_end_dates(
    since: datetime | None,
    until: datetime | None,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """
    Build GitHub sync window: ``(start_commit, start_item, end_date)`` in UTC.

    ``start_item`` is the single lower bound for the unified issues+PRs ``/issues`` fetch;
    ``start_commit`` is the lower bound for the commits stream. Missing bounds mean
    “from beginning” for starts. Naive datetimes are treated as UTC.

    **Closed window** — both ``since`` and ``until`` are set:

    - If ``since <= until``: return ``(since, since, until)`` (same lower bound for both
      streams; explicit end).
    - If ``since > until``: log a warning, discard both CLI bounds, then use the
      **DB watermark** path below. ``end_date`` is ``None``.

    **Otherwise** (no ``since``, or only one side after the rules above):

    - ``end_date`` is ``until`` when ``until`` was provided, else ``None``. A ``None``
      end means “through now” for callers; ``sync_clang_github_activity`` substitutes
      ``timezone.now()`` before fetching.

    - **Starts:** If ``since`` is set (without a valid closed window): ``start_commit``
      and ``start_item`` are both ``since``. If ``since`` is not set: both are
      ``Max(github_* timestamp) + 1 millisecond`` from the DB when a watermark exists, else
      ``None`` (full history). Watermarks use ``Max(github_committed_at)`` and
      ``Max(github_updated_at)`` on ``ClangGithubCommit`` / ``ClangGithubIssueItem``.
    """
    since_aware = _aware_utc(since)
    until_aware = _aware_utc(until)

    if since_aware is not None and until_aware is not None:
        if since_aware > until_aware:
            logger.warning(
                "invalid date range: since (%s) is after until (%s); "
                "using DB cursors; end_date None (sync applies now if needed)",
                since_aware,
                until_aware,
            )
            since_aware, until_aware = None, None
        else:
            return since_aware, since_aware, until_aware

    end_date = until_aware

    if since_aware is None:
        item_wm = start_after_watermark(get_issue_item_watermark())
        commit_wm = start_after_watermark(get_commit_watermark())
    else:
        item_wm = since_aware
        commit_wm = since_aware

    return commit_wm, item_wm, end_date
