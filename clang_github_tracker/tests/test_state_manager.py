"""Tests for clang_github_tracker.state (no DB)."""

from unittest.mock import patch


from clang_github_tracker import state_manager as clang_state


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


def test_compute_state_from_raw_empty_dir(tmp_path):
    """When raw repo dir does not exist, compute_state_from_raw returns nulls."""
    with patch("clang_github_tracker.state_manager.get_raw_repo_dir") as m:
        m.return_value = tmp_path / "nonexistent_repo_dir"
        result = clang_state.compute_state_from_raw()
    assert result[clang_state.KEY_LAST_COMMIT_DATE] is None
    assert result[clang_state.KEY_LAST_ISSUE_DATE] is None
    assert result[clang_state.KEY_LAST_PR_DATE] is None
