"""Tests for fetch_commits_from_github backward pagination (oldest→newest)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from github_activity_tracker.fetcher import fetch_commits_from_github


def test_fetch_commits_single_page_yields_oldest_first():
    """fetch_commits_from_github with single page yields commits in reverse (oldest first)."""
    client = MagicMock()
    # Page 1 has no "last" link (single page)
    client.rest_request_with_all_links.return_value = (
        [
            {"sha": "c3", "commit": {"author": {"date": "2024-01-03T00:00:00Z"}}},
            {"sha": "c2", "commit": {"author": {"date": "2024-01-02T00:00:00Z"}}},
            {"sha": "c1", "commit": {"author": {"date": "2024-01-01T00:00:00Z"}}},
        ],
        {},  # No links = single page
    )
    client.rest_request.side_effect = lambda url: {
        "sha": url.split("/")[-1],
        "stats": {},
    }

    commits = list(fetch_commits_from_github(client, "owner", "repo"))

    # Should yield oldest→newest: c1, c2, c3
    assert [c["sha"] for c in commits] == ["c1", "c2", "c3"]


def test_fetch_commits_next_without_last_forward_pagination():
    """When rel=last is omitted but rel=next is present, follow next for all pages."""
    client = MagicMock()

    client.rest_request_with_all_links.return_value = (
        [{"sha": "c3", "commit": {"author": {"date": "2024-01-03T00:00:00Z"}}}],
        {"next": "https://api.github.com/repos/o/r/commits?page=2"},
    )

    client.rest_request_url_with_all_links.side_effect = [
        (
            [{"sha": "c2", "commit": {"author": {"date": "2024-01-02T00:00:00Z"}}}],
            {"next": "https://api.github.com/repos/o/r/commits?page=3"},
        ),
        (
            [{"sha": "c1", "commit": {"author": {"date": "2024-01-01T00:00:00Z"}}}],
            {},
        ),
    ]

    client.rest_request.side_effect = lambda url: {
        "sha": url.split("/")[-1],
        "stats": {},
    }

    commits = list(fetch_commits_from_github(client, "owner", "repo"))

    assert [c["sha"] for c in commits] == ["c1", "c2", "c3"]
    assert client.rest_request_url_with_all_links.call_count == 2


def test_fetch_commits_multiple_pages_backward_traversal():
    """fetch_commits_from_github walks backward from last page to first."""
    client = MagicMock()

    # Page 1: has "last" link pointing to page 3
    client.rest_request_with_all_links.return_value = (
        [{"sha": "c9", "commit": {"author": {"date": "2024-01-09T00:00:00Z"}}}],
        {
            "next": "https://api.github.com/repos/o/r/commits?page=2",
            "last": "https://api.github.com/repos/o/r/commits?page=3",
        },
    )

    # Page 3 (last): has "prev" pointing to page 2
    # Page 2: has "prev" pointing to page 1
    client.rest_request_url_with_all_links.side_effect = [
        # Page 3
        (
            [{"sha": "c1", "commit": {"author": {"date": "2024-01-01T00:00:00Z"}}}],
            {
                "prev": "https://api.github.com/repos/o/r/commits?page=2",
                "first": "https://api.github.com/repos/o/r/commits?page=1",
            },
        ),
        # Page 2
        (
            [{"sha": "c5", "commit": {"author": {"date": "2024-01-05T00:00:00Z"}}}],
            {
                "prev": "https://api.github.com/repos/o/r/commits?page=1",
                "first": "https://api.github.com/repos/o/r/commits?page=1",
            },
        ),
        # Page 1 is cached, not fetched again
    ]

    client.rest_request.side_effect = lambda url: {
        "sha": url.split("/")[-1],
        "stats": {},
    }

    commits = list(fetch_commits_from_github(client, "owner", "repo"))

    # Should yield oldest→newest: c1 (page 3), c5 (page 2), c9 (page 1 cached)
    assert [c["sha"] for c in commits] == ["c1", "c5", "c9"]
    # Page 1 should NOT be fetched again via rest_request_url_with_all_links
    assert client.rest_request_url_with_all_links.call_count == 2


def test_fetch_commits_caches_first_page():
    """fetch_commits_from_github reuses cached page 1 data when prev returns to page 1."""
    client = MagicMock()

    # Page 1
    page1_data = [
        {"sha": "c3", "commit": {"author": {"date": "2024-01-03T00:00:00Z"}}},
    ]
    client.rest_request_with_all_links.return_value = (
        page1_data,
        {"last": "https://api.github.com/repos/o/r/commits?page=2"},
    )

    # Page 2 (last): prev points back to page 1
    client.rest_request_url_with_all_links.return_value = (
        [{"sha": "c1", "commit": {"author": {"date": "2024-01-01T00:00:00Z"}}}],
        {"prev": "https://api.github.com/repos/o/r/commits?page=1"},
    )

    client.rest_request.side_effect = lambda url: {
        "sha": url.split("/")[-1],
        "stats": {},
    }

    commits = list(fetch_commits_from_github(client, "owner", "repo"))

    # Should yield c1 (page 2), c3 (page 1 from cache)
    assert [c["sha"] for c in commits] == ["c1", "c3"]
    # rest_request_url_with_all_links called only once for page 2
    assert client.rest_request_url_with_all_links.call_count == 1


def test_fetch_commits_filters_by_date_range():
    """fetch_commits_from_github filters commits outside start_time/end_time."""
    client = MagicMock()
    client.rest_request_with_all_links.return_value = (
        [
            {"sha": "c4", "commit": {"author": {"date": "2024-01-04T00:00:00Z"}}},
            {"sha": "c2", "commit": {"author": {"date": "2024-01-02T00:00:00Z"}}},
            {"sha": "c1", "commit": {"author": {"date": "2024-01-01T00:00:00Z"}}},
        ],
        {},
    )
    client.rest_request.side_effect = lambda url: {
        "sha": url.split("/")[-1],
        "stats": {},
    }

    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end = datetime(2024, 1, 3, tzinfo=timezone.utc)
    commits = list(
        fetch_commits_from_github(client, "o", "r", start_time=start, end_time=end)
    )

    # Only c2 is in range [2024-01-02, 2024-01-03]
    assert [c["sha"] for c in commits] == ["c2"]


def test_fetch_commits_handles_304_not_modified():
    """fetch_commits_from_github returns immediately on 304 when using etag_cache."""
    client = MagicMock()
    etag_cache = MagicMock()
    etag_cache.get.return_value = "abc123"

    # 304 response: data is None
    client.rest_request_conditional_with_all_links.return_value = (None, "abc123", {})

    commits = list(fetch_commits_from_github(client, "o", "r", etag_cache=etag_cache))

    assert commits == []
    # Should not attempt to paginate
    client.rest_request_url_with_all_links.assert_not_called()
