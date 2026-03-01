"""Tests for github_activity_tracker.fetcher."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from github_activity_tracker.fetcher import (
    fetch_comments_from_github,
    fetch_commits_from_github,
    fetch_issues_from_github,
    fetch_pr_reviews_from_github,
    fetch_pull_requests_from_github,
    fetch_user_from_github,
)


# --- fetch_user_from_github ---


def test_fetch_user_from_github_by_user_id():
    """fetch_user_from_github with user_id calls /user/{id} and returns user dict."""
    client = MagicMock()
    client.rest_request.return_value = {"id": 1, "login": "u"}
    result = fetch_user_from_github(client, user_id=1)
    assert result == {"id": 1, "login": "u"}
    client.rest_request.assert_called_once_with("/user/1")


def test_fetch_user_from_github_by_username():
    """fetch_user_from_github with username calls /users/{username} and returns user dict."""
    client = MagicMock()
    client.rest_request.return_value = {"id": 2, "login": "alice"}
    result = fetch_user_from_github(client, username="alice")
    assert result == {"id": 2, "login": "alice"}
    client.rest_request.assert_called_with("/users/alice")


def test_fetch_user_from_github_by_email_search():
    """fetch_user_from_github with email searches and then fetches user by id."""
    client = MagicMock()
    client.rest_request.side_effect = [
        {"items": [{"id": 3}]},
        {"id": 3, "login": "bob"},
    ]
    result = fetch_user_from_github(client, email="bob@example.com")
    assert result == {"id": 3, "login": "bob"}
    assert client.rest_request.call_count == 2
    assert "search/users" in client.rest_request.call_args_list[0][0][0]
    assert client.rest_request.call_args_list[1][0][0] == "/user/3"


def test_fetch_user_from_github_returns_none_when_no_criteria():
    """fetch_user_from_github with no user_id/username/email returns None."""
    client = MagicMock()
    result = fetch_user_from_github(client)
    assert result is None
    client.rest_request.assert_not_called()


def test_fetch_user_from_github_returns_none_when_empty_response():
    """fetch_user_from_github returns None when API returns empty/falsy."""
    client = MagicMock()
    client.rest_request.return_value = None
    result = fetch_user_from_github(client, user_id=99)
    assert result is None


# --- fetch_commits_from_github ---


def test_fetch_commits_from_github_yields_commit_dicts():
    """fetch_commits_from_github yields full commit dict from /repos/.../commits/{sha}."""
    client = MagicMock()
    client.rest_request.side_effect = [
        [
            {
                "sha": "abc",
                "commit": {"author": {"date": "2024-01-01T00:00:00Z"}},
            }
        ],
        {
            "sha": "abc",
            "commit": {"message": "msg"},
            "stats": {"additions": 1},
        },
    ]
    items = list(fetch_commits_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["sha"] == "abc"
    assert items[0]["commit"]["message"] == "msg"


def test_fetch_commits_from_github_stops_on_empty_page():
    """fetch_commits_from_github stops when API returns empty list."""
    client = MagicMock()
    client.rest_request.return_value = []
    items = list(fetch_commits_from_github(client, "owner", "repo"))
    assert items == []
    client.rest_request.assert_called_once()


def test_fetch_commits_from_github_includes_since_until_params():
    """fetch_commits_from_github passes since/until when start_time/end_time given."""
    client = MagicMock()
    client.rest_request.return_value = []
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 31, tzinfo=timezone.utc)
    list(fetch_commits_from_github(client, "o", "r", start_time=start, end_time=end))
    call_args = client.rest_request.call_args
    params = call_args[0][1] or {}
    assert "since" in params
    assert "until" in params


def test_fetch_commits_from_github_skips_commit_on_502_503_504():
    """fetch_commits_from_github skips commit and continues when full-commit fetch returns 502/503/504."""
    import requests as req

    client = MagicMock()
    # API returns commits (e.g. newest first); fetcher iterates reversed(), so first
    # full-commit fetch is for the last in this list (def456), second for abc123.
    client.rest_request.side_effect = [
        [
            {
                "sha": "abc123",
                "commit": {"author": {"date": "2024-01-01T00:00:00Z"}},
            },
            {
                "sha": "def456",
                "commit": {"author": {"date": "2024-01-02T00:00:00Z"}},
            },
        ],
        req.exceptions.HTTPError("Bad Gateway", response=MagicMock(status_code=502)),
        {"sha": "abc123", "commit": {"message": "msg1"}, "stats": {"additions": 1}},
    ]
    items = list(fetch_commits_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["sha"] == "abc123"


def test_fetch_commits_from_github_reraises_non_server_error_http():
    """fetch_commits_from_github re-raises HTTPError when status is not 502/503/504."""
    import requests as req

    client = MagicMock()
    client.rest_request.side_effect = [
        [{"sha": "abc", "commit": {"author": {"date": "2024-01-01T00:00:00Z"}}}],
        req.exceptions.HTTPError("Forbidden", response=MagicMock(status_code=403)),
    ]
    with pytest.raises(req.exceptions.HTTPError):
        list(fetch_commits_from_github(client, "o", "r"))


# --- fetch_comments_from_github ---


def test_fetch_comments_from_github_returns_list():
    """fetch_comments_from_github returns list of comment dicts."""
    client = MagicMock()
    client.rest_request.return_value = [
        {"id": 1, "body": "c1", "created_at": "2024-01-01T00:00:00Z"},
        {"id": 2, "body": "c2", "created_at": "2024-01-02T00:00:00Z"},
    ]
    result = fetch_comments_from_github(client, "o", "r", issue_number=1)
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["body"] == "c2"


def test_fetch_comments_from_github_stops_on_empty_page():
    """fetch_comments_from_github returns empty list when API returns empty."""
    client = MagicMock()
    client.rest_request.return_value = []
    result = fetch_comments_from_github(client, "o", "r", issue_number=5)
    assert result == []


def test_fetch_comments_from_github_calls_correct_endpoint():
    """fetch_comments_from_github calls .../issues/{number}/comments."""
    client = MagicMock()
    client.rest_request.return_value = []
    fetch_comments_from_github(client, "owner", "repo", issue_number=42)
    client.rest_request.assert_called_once()
    assert "/repos/owner/repo/issues/42/comments" in client.rest_request.call_args[0][0]


# --- fetch_issues_from_github ---


def test_fetch_issues_from_github_yields_issue_dicts():
    """fetch_issues_from_github yields issue dicts (excluding PRs)."""
    client = MagicMock()
    # No "pull_request" key = plain issue (fetcher filters by "pull_request" in i)
    # Must include updated_at/created_at or fetcher skips the issue
    client.rest_request.side_effect = [
        [{"number": 1, "title": "Issue 1", "updated_at": "2024-06-01T00:00:00Z"}],
        [],  # comments for issue 1
    ]
    items = list(fetch_issues_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["number"] == 1
    assert "comments" in items[0]


def test_fetch_issues_from_github_filters_out_pulls():
    """fetch_issues_from_github filters out items that have pull_request key."""
    client = MagicMock()
    client.rest_request.side_effect = [
        [
            {"number": 1, "pull_request": {}},
            {"number": 2, "updated_at": "2024-06-01T00:00:00Z"},
        ],
        [],  # comments for issue 2
    ]
    items = list(fetch_issues_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["number"] == 2


def test_fetch_issues_from_github_stops_on_empty_page():
    """fetch_issues_from_github stops when API returns empty list."""
    client = MagicMock()
    client.rest_request.return_value = []
    items = list(fetch_issues_from_github(client, "owner", "repo"))
    assert items == []


# --- fetch_pr_reviews_from_github ---


def test_fetch_pr_reviews_from_github_returns_list():
    """fetch_pr_reviews_from_github returns list of review/comment dicts."""
    client = MagicMock()
    client.rest_request.return_value = [
        {"id": 1, "body": "LGTM", "created_at": "2024-01-01T00:00:00Z"},
    ]
    result = fetch_pr_reviews_from_github(client, "o", "r", pr_number=1)
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_fetch_pr_reviews_from_github_stops_on_empty_page():
    """fetch_pr_reviews_from_github returns empty list when API returns empty."""
    client = MagicMock()
    client.rest_request.return_value = []
    result = fetch_pr_reviews_from_github(client, "o", "r", pr_number=2)
    assert result == []


def test_fetch_pr_reviews_from_github_calls_pulls_comments():
    """fetch_pr_reviews_from_github calls .../pulls/{number}/comments."""
    client = MagicMock()
    client.rest_request.return_value = []
    fetch_pr_reviews_from_github(client, "owner", "repo", pr_number=3)
    client.rest_request.assert_called_once()
    assert "/repos/owner/repo/pulls/3/comments" in client.rest_request.call_args[0][0]


# --- fetch_pull_requests_from_github ---


def test_fetch_pull_requests_from_github_yields_pr_dicts():
    """fetch_pull_requests_from_github yields PR dicts with comments and reviews."""
    client = MagicMock()
    client.rest_request.side_effect = [
        [
            {
                "number": 1,
                "updated_at": "2024-06-01T00:00:00Z",
                "created_at": "2024-05-01T00:00:00Z",
            },
        ],
        [],  # comments for PR 1
        [],  # reviews for PR 1
    ]
    items = list(fetch_pull_requests_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["number"] == 1
    assert "comments" in items[0]
    assert "reviews" in items[0]


def test_fetch_pull_requests_from_github_stops_on_empty_page():
    """fetch_pull_requests_from_github stops when API returns empty list."""
    client = MagicMock()
    client.rest_request.return_value = []
    items = list(fetch_pull_requests_from_github(client, "owner", "repo"))
    assert items == []


def test_fetch_pull_requests_from_github_calls_correct_endpoint():
    """fetch_pull_requests_from_github calls .../pulls with state=all."""
    client = MagicMock()
    client.rest_request.return_value = []
    list(fetch_pull_requests_from_github(client, "owner", "repo"))
    call_args = client.rest_request.call_args
    assert "/repos/owner/repo/pulls" in call_args[0][0]
    params = call_args[0][1] or {}
    assert params["state"] == "all"
