"""Tests for sync_issues_and_prs unified sync function."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from github_activity_tracker.sync.issues_and_prs import (
    sync_issues_and_prs,
)


@patch("github_activity_tracker.sync.issues_and_prs.get_github_client")
@patch("github_activity_tracker.sync.issues_and_prs.fetcher")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_issue_jsons")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_pr_jsons")
def test_sync_issues_and_prs_processes_both_types(
    mock_existing_prs, mock_existing_issues, mock_fetcher, mock_get_client
):
    """sync_issues_and_prs routes items by key to issue or PR processing."""
    mock_repo = MagicMock()
    mock_repo.owner_account.username = "owner"
    mock_repo.repo_name = "repo"
    mock_repo.issues.order_by.return_value.first.return_value = None
    mock_repo.pull_requests.order_by.return_value.first.return_value = None

    mock_existing_issues.return_value = (0, [])
    mock_existing_prs.return_value = (0, [])

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    # Yield one issue and one PR
    mock_fetcher.fetch_issues_and_prs_from_github.return_value = [
        {"issue_info": {"number": 1}, "comments": []},
        {"pr_info": {"number": 2}, "comments": [], "reviews": []},
    ]

    with patch(
        "github_activity_tracker.sync.issues_and_prs._process_issue_data"
    ) as mock_proc_issue, patch(
        "github_activity_tracker.sync.issues_and_prs._process_pr_data"
    ) as mock_proc_pr, patch(
        "github_activity_tracker.sync.issues_and_prs.save_issue_raw_source"
    ), patch(
        "github_activity_tracker.sync.issues_and_prs.save_pr_raw_source"
    ), patch(
        "github_activity_tracker.sync.issues_and_prs.get_issue_json_path"
    ) as mock_issue_path, patch(
        "github_activity_tracker.sync.issues_and_prs.get_pr_json_path"
    ) as mock_pr_path:

        mock_issue_path.return_value = MagicMock()
        mock_pr_path.return_value = MagicMock()

        result = sync_issues_and_prs(mock_repo)

    assert result == {"issues": [1], "pull_requests": [2]}
    mock_proc_issue.assert_called_once()
    mock_proc_pr.assert_called_once()


@patch("github_activity_tracker.sync.issues_and_prs.get_github_client")
@patch("github_activity_tracker.sync.issues_and_prs.fetcher")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_issue_jsons")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_pr_jsons")
def test_sync_issues_and_prs_uses_max_start_date(
    mock_existing_prs, mock_existing_issues, mock_fetcher, mock_get_client
):
    """sync_issues_and_prs uses the later of last_issue and last_pr (+1s) as start_date."""
    mock_repo = MagicMock()
    mock_repo.owner_account.username = "owner"
    mock_repo.repo_name = "repo"

    # Last issue updated at 2024-01-05
    mock_last_issue = MagicMock()
    mock_last_issue.issue_updated_at = datetime(2024, 1, 5, tzinfo=timezone.utc)
    mock_repo.issues.order_by.return_value.first.return_value = mock_last_issue

    # Last PR updated at 2024-01-03 (older than last issue)
    mock_last_pr = MagicMock()
    mock_last_pr.pr_updated_at = datetime(2024, 1, 3, tzinfo=timezone.utc)
    mock_repo.pull_requests.order_by.return_value.first.return_value = mock_last_pr

    mock_existing_issues.return_value = (0, [])
    mock_existing_prs.return_value = (0, [])

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_fetcher.fetch_issues_and_prs_from_github.return_value = []

    sync_issues_and_prs(mock_repo)

    # Should use max(issue_date, pr_date) → 2024-01-05 + 1s
    call_args = mock_fetcher.fetch_issues_and_prs_from_github.call_args
    start_date = call_args[0][3]  # Fourth positional arg
    assert start_date == datetime(2024, 1, 5, 0, 0, 1, tzinfo=timezone.utc)


@patch("github_activity_tracker.sync.issues_and_prs.get_github_client")
@patch("github_activity_tracker.sync.issues_and_prs.fetcher")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_issue_jsons")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_pr_jsons")
def test_sync_issues_and_prs_processes_existing_jsons_first(
    mock_existing_prs, mock_existing_issues, mock_fetcher, mock_get_client
):
    """sync_issues_and_prs processes leftover JSON files before fetching from GitHub."""
    mock_repo = MagicMock()
    mock_repo.owner_account.username = "owner"
    mock_repo.repo_name = "repo"
    mock_repo.issues.order_by.return_value.first.return_value = None
    mock_repo.pull_requests.order_by.return_value.first.return_value = None

    # Existing JSONs found
    mock_existing_issues.return_value = (2, [10, 11])
    mock_existing_prs.return_value = (1, [20])

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_fetcher.fetch_issues_and_prs_from_github.return_value = []

    result = sync_issues_and_prs(mock_repo)

    # Should include existing numbers in result
    assert 10 in result["issues"]
    assert 11 in result["issues"]
    assert 20 in result["pull_requests"]
    mock_existing_issues.assert_called_once_with(mock_repo)
    mock_existing_prs.assert_called_once_with(mock_repo)


@patch("github_activity_tracker.sync.issues_and_prs.get_github_client")
@patch("github_activity_tracker.sync.issues_and_prs.fetcher")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_issue_jsons")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_pr_jsons")
def test_sync_issues_and_prs_respects_override_start_date(
    mock_existing_prs, mock_existing_issues, mock_fetcher, mock_get_client
):
    """sync_issues_and_prs uses provided start_date instead of deriving from DB."""
    mock_repo = MagicMock()
    mock_repo.owner_account.username = "owner"
    mock_repo.repo_name = "repo"

    mock_existing_issues.return_value = (0, [])
    mock_existing_prs.return_value = (0, [])

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_fetcher.fetch_issues_and_prs_from_github.return_value = []

    override_start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    sync_issues_and_prs(mock_repo, start_date=override_start)

    # Should NOT query DB for last issue/PR
    mock_repo.issues.order_by.assert_not_called()
    mock_repo.pull_requests.order_by.assert_not_called()

    # Should pass override_start to fetcher
    call_args = mock_fetcher.fetch_issues_and_prs_from_github.call_args
    assert call_args[0][3] == override_start


@patch("github_activity_tracker.sync.issues_and_prs.get_github_client")
@patch("github_activity_tracker.sync.issues_and_prs.fetcher")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_issue_jsons")
@patch("github_activity_tracker.sync.issues_and_prs._process_existing_pr_jsons")
def test_sync_issues_and_prs_saves_and_removes_json_files(
    mock_existing_prs, mock_existing_issues, mock_fetcher, mock_get_client
):
    """sync_issues_and_prs writes JSON, processes, then removes file for each item."""
    mock_repo = MagicMock()
    mock_repo.owner_account.username = "owner"
    mock_repo.repo_name = "repo"
    mock_repo.issues.order_by.return_value.first.return_value = None
    mock_repo.pull_requests.order_by.return_value.first.return_value = None

    mock_existing_issues.return_value = (0, [])
    mock_existing_prs.return_value = (0, [])

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_fetcher.fetch_issues_and_prs_from_github.return_value = [
        {"issue_info": {"number": 1}, "comments": []},
    ]

    mock_json_path = MagicMock()

    with patch(
        "github_activity_tracker.sync.issues_and_prs._process_issue_data"
    ), patch(
        "github_activity_tracker.sync.issues_and_prs.save_issue_raw_source"
    ), patch(
        "github_activity_tracker.sync.issues_and_prs.get_issue_json_path",
        return_value=mock_json_path,
    ):

        sync_issues_and_prs(mock_repo)

    # Should write, then unlink
    mock_json_path.parent.mkdir.assert_called_once()
    mock_json_path.write_text.assert_called_once()
    mock_json_path.unlink.assert_called_once()
