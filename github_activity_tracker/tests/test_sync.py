"""Tests for github_activity_tracker.sync (sync_github and date forwarding)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from github_activity_tracker.sync import sync_github


def test_sync_github_passes_start_date_end_date_to_sync_modules():
    """sync_github forwards start_date and end_date to sync_commits and sync_issues_and_prs."""
    mock_repo = MagicMock()
    start = datetime(2024, 1, 1)
    end = datetime(2024, 12, 31)
    with patch("github_activity_tracker.sync.sync_repos") as m_repos, patch(
        "github_activity_tracker.sync.sync_commits"
    ) as m_commits, patch(
        "github_activity_tracker.sync.sync_issues_and_prs"
    ) as m_issues_and_prs:
        m_issues_and_prs.return_value = {"issues": [], "pull_requests": []}
        result = sync_github(mock_repo, start_date=start, end_date=end)

    m_repos.assert_called_once_with(mock_repo)
    m_commits.assert_called_once_with(mock_repo, start_date=start, end_date=end)
    m_issues_and_prs.assert_called_once_with(mock_repo, start_date=start, end_date=end)
    assert result == {"issues": [], "pull_requests": []}


def test_sync_github_calls_sync_without_dates_when_none():
    """sync_github calls sync_commits and sync_issues_and_prs with start_date and end_date None when not provided."""
    mock_repo = MagicMock()
    with patch("github_activity_tracker.sync.sync_repos"), patch(
        "github_activity_tracker.sync.sync_commits"
    ) as m_commits, patch(
        "github_activity_tracker.sync.sync_issues_and_prs"
    ) as m_issues_and_prs:
        m_issues_and_prs.return_value = {"issues": [1, 2], "pull_requests": [3]}
        result = sync_github(mock_repo)

    m_commits.assert_called_once_with(mock_repo, start_date=None, end_date=None)
    m_issues_and_prs.assert_called_once_with(mock_repo, start_date=None, end_date=None)
    assert result == {"issues": [1, 2], "pull_requests": [3]}


def test_sync_github_returns_issues_and_prs_dict():
    """sync_github returns dict with issues and pull_requests keys from sync_issues_and_prs."""
    mock_repo = MagicMock()
    with patch("github_activity_tracker.sync.sync_repos"), patch(
        "github_activity_tracker.sync.sync_commits"
    ), patch("github_activity_tracker.sync.sync_issues_and_prs") as m_issues_and_prs:
        m_issues_and_prs.return_value = {"issues": [10, 20], "pull_requests": [30, 40]}
        result = sync_github(mock_repo)

    assert result == {"issues": [10, 20], "pull_requests": [30, 40]}
