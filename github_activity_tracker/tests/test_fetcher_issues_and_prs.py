"""Tests for fetch_issues_and_prs_from_github unified fetcher."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from github_activity_tracker.fetcher import fetch_issues_and_prs_from_github


def test_fetch_issues_and_prs_routes_issue_correctly():
    """fetch_issues_and_prs_from_github yields issue with issue_info key when no pull_request key."""
    client = MagicMock()
    client.rest_request_with_link.return_value = (
        [
            {
                "number": 1,
                "updated_at": "2024-01-01T00:00:00Z",
                "title": "Bug",
            }
        ],
        None,  # No next page
    )
    client.rest_request.side_effect = [
        {"number": 1, "title": "Bug", "body": "Full issue"},  # Full issue detail
        [],  # Comments
    ]

    items = list(fetch_issues_and_prs_from_github(client, "owner", "repo"))

    assert len(items) == 1
    assert "issue_info" in items[0]
    assert "pr_info" not in items[0]
    assert items[0]["issue_info"]["number"] == 1
    assert items[0]["comments"] == []


def test_fetch_issues_and_prs_routes_pr_correctly():
    """fetch_issues_and_prs_from_github yields PR with pr_info key when pull_request key present."""
    client = MagicMock()
    client.rest_request_with_link.return_value = (
        [
            {
                "number": 2,
                "updated_at": "2024-01-02T00:00:00Z",
                "title": "Feature",
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/2"},
            }
        ],
        None,
    )
    client.rest_request.side_effect = [
        {"number": 2, "title": "Feature", "body": "Full PR"},  # Full PR detail
        [],  # Comments
        [],  # Reviews
    ]

    items = list(fetch_issues_and_prs_from_github(client, "owner", "repo"))

    assert len(items) == 1
    assert "pr_info" in items[0]
    assert "issue_info" not in items[0]
    assert items[0]["pr_info"]["number"] == 2
    assert items[0]["comments"] == []
    assert items[0]["reviews"] == []


def test_fetch_issues_and_prs_fetches_both_in_one_call():
    """fetch_issues_and_prs_from_github processes both issues and PRs from single /issues list."""
    client = MagicMock()
    client.rest_request_with_link.return_value = (
        [
            {"number": 1, "updated_at": "2024-01-01T00:00:00Z", "title": "Issue"},
            {
                "number": 2,
                "updated_at": "2024-01-02T00:00:00Z",
                "title": "PR",
                "pull_request": {"url": "..."},
            },
        ],
        None,
    )
    client.rest_request.side_effect = [
        {"number": 1, "title": "Issue"},  # Issue detail
        [],  # Issue comments
        {"number": 2, "title": "PR"},  # PR detail
        [],  # PR comments
        [],  # PR reviews
    ]

    items = list(fetch_issues_and_prs_from_github(client, "o", "r"))

    assert len(items) == 2
    assert "issue_info" in items[0]
    assert "pr_info" in items[1]


def test_fetch_issues_and_prs_uses_direction_asc():
    """fetch_issues_and_prs_from_github requests items with direction=asc (oldest first)."""
    client = MagicMock()
    client.rest_request_with_link.return_value = ([], None)

    list(fetch_issues_and_prs_from_github(client, "owner", "repo"))

    # Check the params argument (second positional arg)
    call_args = client.rest_request_with_link.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params")
    assert params["direction"] == "asc"
    assert params["sort"] == "updated"


def test_fetch_issues_and_prs_filters_by_date_range():
    """fetch_issues_and_prs_from_github filters items outside start_time/end_time."""
    client = MagicMock()
    client.rest_request_with_link.return_value = (
        [
            {"number": 1, "updated_at": "2024-01-01T00:00:00Z"},
            {"number": 2, "updated_at": "2024-01-05T00:00:00Z"},
            {"number": 3, "updated_at": "2024-01-10T00:00:00Z"},
        ],
        None,
    )
    client.rest_request.side_effect = [
        {"number": 2},  # Only #2 in range
        [],  # Comments
    ]

    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end = datetime(2024, 1, 8, tzinfo=timezone.utc)
    items = list(
        fetch_issues_and_prs_from_github(
            client, "o", "r", start_time=start, end_time=end
        )
    )

    assert len(items) == 1
    assert items[0]["issue_info"]["number"] == 2


def test_fetch_issues_and_prs_paginates_with_link_header():
    """fetch_issues_and_prs_from_github follows Link rel=next for pagination."""
    client = MagicMock()
    client.rest_request_with_link.return_value = (
        [{"number": 1, "updated_at": "2024-01-01T00:00:00Z"}],
        "https://api.github.com/page=2",
    )
    client.rest_request_url.return_value = (
        [{"number": 2, "updated_at": "2024-01-02T00:00:00Z"}],
        None,
    )
    client.rest_request.side_effect = [
        {"number": 1},
        [],
        {"number": 2},
        [],
    ]

    items = list(fetch_issues_and_prs_from_github(client, "o", "r"))

    assert len(items) == 2
    client.rest_request_url.assert_called_once_with("https://api.github.com/page=2")


def test_fetch_issues_and_prs_handles_304_not_modified():
    """fetch_issues_and_prs_from_github skips page on 304 when using etag_cache."""
    client = MagicMock()
    etag_cache = MagicMock()
    etag_cache.get.return_value = "etag123"

    # First page: 304, second page: empty (end of pagination)
    client.rest_request_conditional_with_link.side_effect = [
        (None, "etag123", None),  # Page 1: 304
        ([], "new_etag", None),  # Page 2: empty list (stops pagination)
    ]

    items = list(
        fetch_issues_and_prs_from_github(client, "o", "r", etag_cache=etag_cache)
    )

    assert items == []
    # Should have tried page 1 (304) and page 2 (empty)
    assert client.rest_request_conditional_with_link.call_count == 2
