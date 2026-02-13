"""Tests for github_activity_tracker.sync.repos."""

import pytest
from unittest.mock import MagicMock, patch

from github_activity_tracker.sync.repos import sync_repos


@pytest.mark.django_db
def test_sync_repos_updates_repo_fields(github_repository):
    """sync_repos fetches repo info and updates stars, forks, description, dates."""
    mock_client = MagicMock()
    mock_client.get_repository_info.return_value = {
        "stargazers_count": 100,
        "forks_count": 5,
        "description": "A great repo",
        "pushed_at": "2024-01-15T10:00:00Z",
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2024-01-15T10:00:00Z",
    }
    with patch(
        "github_activity_tracker.sync.repos.get_github_client",
        return_value=mock_client,
    ):
        sync_repos(github_repository)
    github_repository.refresh_from_db()
    assert github_repository.stars == 100
    assert github_repository.forks == 5
    assert github_repository.description == "A great repo"
    assert github_repository.repo_pushed_at is not None
    assert github_repository.repo_created_at is not None
    assert github_repository.repo_updated_at is not None


@pytest.mark.django_db
def test_sync_repos_calls_get_repository_info_with_owner_repo(
    github_repository,
):
    """sync_repos calls client.get_repository_info(owner, repo_name) from repo.owner_account.username."""
    mock_client = MagicMock()
    mock_client.get_repository_info.return_value = {
        "stargazers_count": 0,
        "forks_count": 0,
        "description": "",
        "pushed_at": None,
        "created_at": None,
        "updated_at": None,
    }
    with patch(
        "github_activity_tracker.sync.repos.get_github_client",
        return_value=mock_client,
    ):
        sync_repos(github_repository)
    mock_client.get_repository_info.assert_called_once()
    call_args = mock_client.get_repository_info.call_args[0]
    assert call_args[0] == github_repository.owner_account.username
    assert call_args[1] == github_repository.repo_name


@pytest.mark.django_db
def test_sync_repos_raises_on_connection_exception(github_repository):
    """sync_repos re-raises ConnectionException from client."""
    from github_ops.client import ConnectionException

    mock_client = MagicMock()
    mock_client.get_repository_info.side_effect = ConnectionException("network error")
    with patch(
        "github_activity_tracker.sync.repos.get_github_client",
        return_value=mock_client,
    ):
        with pytest.raises(ConnectionException, match="network error"):
            sync_repos(github_repository)


@pytest.mark.django_db
def test_sync_repos_raises_on_rate_limit_exception(github_repository):
    """sync_repos re-raises RateLimitException from client."""
    from github_ops.client import RateLimitException

    mock_client = MagicMock()
    mock_client.get_repository_info.side_effect = RateLimitException("rate limited")
    with patch(
        "github_activity_tracker.sync.repos.get_github_client",
        return_value=mock_client,
    ):
        with pytest.raises(RateLimitException, match="rate limited"):
            sync_repos(github_repository)
