"""Tests for clang_github_tracker.state_manager (DB-backed date resolution)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from clang_github_tracker import state_manager as clang_state
from clang_github_tracker.models import ClangGithubCommit, ClangGithubIssueItem


def test_parse_iso_valid():
    """parse_iso returns datetime for valid ISO strings."""
    dt = clang_state.parse_iso("2024-01-15T10:30:00Z")
    assert dt is not None
    assert dt.year == 2024 and dt.month == 1 and dt.day == 15
    dt2 = clang_state.parse_iso("2024-06-01T00:00:00+00:00")
    assert dt2 is not None
    assert dt2.month == 6


def test_parse_iso_invalid_or_empty():
    """parse_iso returns None for empty or invalid input."""
    assert clang_state.parse_iso(None) is None
    assert clang_state.parse_iso("") is None
    assert clang_state.parse_iso("  ") is None
    assert clang_state.parse_iso("not-a-date") is None


@pytest.mark.django_db
def test_resolve_empty_db_no_since_until():
    """Empty tables → None starts; end None until caller passes --until."""
    ClangGithubIssueItem.objects.all().delete()
    ClangGithubCommit.objects.all().delete()
    sc, si, end = clang_state.resolve_start_end_dates(None, None)
    assert sc is None and si is None
    assert end is None


@pytest.mark.django_db
def test_resolve_db_watermark_plus_one_second():
    """Max github fields drive start = max + 1s."""
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
    sc, si, end = clang_state.resolve_start_end_dates(None, None)
    assert sc == base + timedelta(seconds=1)
    assert si == base + timedelta(seconds=1)


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
    ClangGithubIssueItem.objects.create(
        number=99,
        is_pull_request=False,
        github_updated_at=timezone.now() - timedelta(hours=1),
    )
    since = timezone.now()
    until = timezone.now() - timedelta(days=1)
    with caplog.at_level("WARNING"):
        sc, si, end = clang_state.resolve_start_end_dates(since, until)
    assert any("invalid date range" in r.getMessage() for r in caplog.records)
    assert end is None
    assert sc is not None and si is not None


@pytest.mark.django_db
def test_resolve_since_floor_without_until():
    """Only since: starts are max(DB+1s, since)."""
    base = timezone.now() - timedelta(days=30)
    ClangGithubIssueItem.objects.create(
        number=2,
        is_pull_request=False,
        github_updated_at=base,
    )
    since = timezone.now() - timedelta(days=1)
    sc, si, _end = clang_state.resolve_start_end_dates(since, None)
    assert si is not None
    assert si >= since
