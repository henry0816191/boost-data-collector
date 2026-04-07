"""Tests for clang_github_tracker.state_manager (DB-backed date resolution)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from clang_github_tracker import state_manager as clang_state
from clang_github_tracker.models import ClangGithubCommit, ClangGithubIssueItem


@pytest.mark.django_db
def test_resolve_empty_db_no_since_until():
    """Empty tables → None starts; end None until caller passes --until."""
    ClangGithubIssueItem.objects.all().delete()
    ClangGithubCommit.objects.all().delete()
    sc, si, end = clang_state.resolve_start_end_dates(None, None)
    assert sc is None and si is None
    assert end is None


@pytest.mark.django_db
def test_resolve_db_watermark_plus_one_millisecond():
    """Max github fields drive start = max + 1ms (API lower bound)."""
    base = timezone.now() - timedelta(days=1)
    ClangGithubIssueItem.objects.create(
        number=1,
        is_pull_request=False,
        github_created_at=base,
        github_updated_at=base,
    )
    ClangGithubCommit.objects.create(
        sha="a" * 40,
        github_committed_at=base,
    )
    sc, si, _end = clang_state.resolve_start_end_dates(None, None)
    delta = timedelta(milliseconds=1)
    assert sc == base + delta
    assert si == base + delta


@pytest.mark.django_db
def test_resolve_both_since_until_closed_window():
    """Both bounds valid → same since for commit and item; until as end."""
    since = timezone.now() - timedelta(days=10)
    until = timezone.now() - timedelta(days=5)
    sc, si, end = clang_state.resolve_start_end_dates(since, until)
    assert sc == since
    assert si == since
    assert end == until


@pytest.mark.django_db
def test_resolve_invalid_range_clears_bounds(caplog):
    """since > until → warning and DB-based resolution."""
    wm = timezone.now() - timedelta(hours=1)
    ClangGithubIssueItem.objects.create(
        number=99,
        is_pull_request=False,
        github_updated_at=wm,
    )
    ClangGithubCommit.objects.create(
        sha="c" * 40,
        github_committed_at=wm,
    )
    since = timezone.now()
    until = timezone.now() - timedelta(days=1)
    with caplog.at_level("WARNING"):
        sc, si, end = clang_state.resolve_start_end_dates(since, until)
    assert any("invalid date range" in r.getMessage() for r in caplog.records)
    assert end is None
    delta = timedelta(milliseconds=1)
    assert sc == wm + delta
    assert si == wm + delta


@pytest.mark.django_db
def test_resolve_since_floor_without_until():
    """Only since: both starts equal the explicit since; DB watermarks are ignored."""
    base = timezone.now() - timedelta(days=30)
    ClangGithubIssueItem.objects.create(
        number=2,
        is_pull_request=False,
        github_updated_at=base,
    )
    since = timezone.now() - timedelta(days=1)
    sc, si, end = clang_state.resolve_start_end_dates(since, None)
    assert sc == since
    assert si == since
    assert end is None
