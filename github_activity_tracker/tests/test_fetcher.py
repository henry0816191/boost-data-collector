"""Tests for github_activity_tracker.fetcher."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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


def test_fetch_commits_from_github_with_etag_cache_304_yields_nothing():
    """When etag_cache is passed and rest_request_conditional returns 304, page is skipped
    and next page is requested; when next page returns empty, no items yielded and set not called.
    """
    client = MagicMock()
    # Page 1: 304 -> skip; page 2: empty -> break. No items, no etag_cache.set.
    client.rest_request_conditional.side_effect = [
        (None, 'W/"cached"'),  # page 1: 304
        ([], None),  # page 2: empty, stops loop
    ]
    etag_cache = MagicMock()
    etag_cache.get.return_value = 'W/"cached"'
    with patch("github_activity_tracker.fetcher.time.sleep"):
        items = list(fetch_commits_from_github(client, "o", "r", etag_cache=etag_cache))
    assert items == []
    assert client.rest_request_conditional.call_count == 2
    # Ensure we requested page 1 then page 2 (no re-requesting the same page).
    call1_params = client.rest_request_conditional.call_args_list[0][1]["params"]
    call2_params = client.rest_request_conditional.call_args_list[1][1]["params"]
    assert call1_params["page"] == 1
    assert call2_params["page"] == 2
    etag_cache.set.assert_not_called()


def test_fetch_commits_from_github_with_etag_cache_200_yields_and_sets():
    """When etag_cache is passed and rest_request_conditional returns 200, yields items and calls set
    only after the page's items have been consumed (checkpoint deferred).
    """
    client = MagicMock()
    # Two items on page 1 so we can assert set() is not called until after both are consumed.
    client.rest_request_conditional.side_effect = [
        (
            [
                {"sha": "abc", "commit": {"author": {"date": "2024-06-01T00:00:00Z"}}},
                {"sha": "def", "commit": {"author": {"date": "2024-06-02T00:00:00Z"}}},
            ],
            "W/new_etag",
        ),
    ]
    client.rest_request.side_effect = [
        {"sha": "abc", "commit": {"message": "msg"}, "stats": {"additions": 1}},
        {"sha": "def", "commit": {"message": "msg2"}, "stats": {"additions": 2}},
    ]
    etag_cache = MagicMock()
    etag_cache.get.return_value = None
    with patch("github_activity_tracker.fetcher.time.sleep"):
        gen = fetch_commits_from_github(client, "o", "r", etag_cache=etag_cache)
        # Consume first item only; checkpoint must not be written yet.
        first = next(gen)
        etag_cache.set.assert_not_called()
        # Consume second item; set still not called until we advance past the last yield.
        second = next(gen)
        etag_cache.set.assert_not_called()
        # Advancing again runs the code after the for-loop (etag_cache.set) then exits.
        with pytest.raises(StopIteration):
            next(gen)
        etag_cache.set.assert_called_once()
    assert first["sha"] == "abc"
    assert second["sha"] == "def"
    call_args = etag_cache.set.call_args[0]
    assert call_args[0] == "commits"
    assert call_args[1] == 1
    assert call_args[4] == "W/new_etag"


def test_fetch_commits_from_github_aborts_on_502_503_504():
    """fetch_commits_from_github raises HTTPError on 502/503/504 so page is not checkpointed and can be retried."""
    import requests as req

    client = MagicMock()
    # API returns commits (e.g. newest first); fetcher iterates reversed(), so first
    # full-commit fetch is for the last in this list (def456). That fetch returns 502 → abort.
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
    ]
    with pytest.raises(req.exceptions.HTTPError):
        list(fetch_commits_from_github(client, "o", "r"))


def test_fetch_commits_from_github_5xx_with_etag_cache_does_not_checkpoint():
    """When etag_cache is enabled and a 5xx aborts during full-commit fetch, etag_cache.set is not called."""
    import requests as req

    client = MagicMock()
    client.rest_request_conditional.side_effect = [
        (
            [{"sha": "abc", "commit": {"author": {"date": "2024-06-01T00:00:00Z"}}}],
            "W/new_etag",
        ),
    ]
    client.rest_request.side_effect = req.exceptions.HTTPError(
        "Bad Gateway", response=MagicMock(status_code=502)
    )
    etag_cache = MagicMock()
    etag_cache.get.return_value = None
    with patch("github_activity_tracker.fetcher.time.sleep"):
        with pytest.raises(req.exceptions.HTTPError):
            list(fetch_commits_from_github(client, "o", "r", etag_cache=etag_cache))
    etag_cache.set.assert_not_called()


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
    """fetch_issues_from_github yields nested { issue_info, comments } dicts."""
    client = MagicMock()
    # First page via Link-header API (list + next_url); then full issue GET; then comments
    client.rest_request_with_link.return_value = (
        [{"number": 1, "title": "Issue 1", "updated_at": "2024-06-01T00:00:00Z"}],
        None,
    )
    client.rest_request.side_effect = [
        {"number": 1, "title": "Issue 1", "updated_at": "2024-06-01T00:00:00Z"},
        [],  # comments for issue 1
    ]
    items = list(fetch_issues_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["issue_info"]["number"] == 1
    assert "comments" in items[0]
    assert items[0]["comments"] == []


def test_fetch_issues_from_github_filters_out_pulls():
    """fetch_issues_from_github filters out items that have pull_request key."""
    client = MagicMock()
    client.rest_request_with_link.return_value = (
        [
            {"number": 1, "pull_request": {}},
            {"number": 2, "updated_at": "2024-06-01T00:00:00Z"},
        ],
        None,
    )
    client.rest_request.side_effect = [
        {"number": 2, "updated_at": "2024-06-01T00:00:00Z"},  # full issue for #2
        [],  # comments for issue 2
    ]
    items = list(fetch_issues_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["issue_info"]["number"] == 2


def test_fetch_issues_from_github_stops_on_empty_page():
    """fetch_issues_from_github stops when API returns empty list."""
    client = MagicMock()
    client.rest_request_with_link.return_value = ([], None)
    items = list(fetch_issues_from_github(client, "owner", "repo"))
    assert items == []
    client.rest_request.assert_not_called()


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
    """fetch_pull_requests_from_github yields nested { pr_info, comments, reviews } dicts."""
    client = MagicMock()
    client.rest_request.side_effect = [
        [
            {
                "number": 1,
                "updated_at": "2024-06-01T00:00:00Z",
                "created_at": "2024-05-01T00:00:00Z",
            },
        ],
        {
            "number": 1,
            "updated_at": "2024-06-01T00:00:00Z",
            "created_at": "2024-05-01T00:00:00Z",
        },  # full PR
        [],  # comments for PR 1
        [],  # reviews for PR 1
    ]
    items = list(fetch_pull_requests_from_github(client, "o", "r"))
    assert len(items) == 1
    assert items[0]["pr_info"]["number"] == 1
    assert "comments" in items[0]
    assert "reviews" in items[0]
    assert items[0]["comments"] == []
    assert items[0]["reviews"] == []


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
