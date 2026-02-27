"""Tests for boost_mailing_list_tracker.fetcher.

Covers edge cases and boundaries: empty inputs, date filtering,
format_email with missing/None/invalid data, _get_start_date_from_db format.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from boost_mailing_list_tracker import fetcher


# --- _filter_by_date ---


def test_filter_by_date_empty_results():
    """_filter_by_date with empty results returns empty list and should_stop=False."""
    filtered, stop = fetcher._filter_by_date([], "2024-01-01", "2024-12-31")
    assert filtered == []
    assert stop is False


def test_filter_by_date_empty_start_and_end():
    """_filter_by_date with empty start_date and end_date includes all items."""
    results = [
        {"date": "2024-06-01T12:00:00Z"},
        {"date": "2024-06-02T12:00:00Z"},
    ]
    filtered, stop = fetcher._filter_by_date(results, "", "")
    assert len(filtered) == 2
    assert stop is False


def test_filter_by_date_stop_when_before_start():
    """_filter_by_date sets should_stop when item date is before start_date."""
    results = [
        {"date": "2024-06-15T12:00:00Z"},
        {"date": "2024-06-01T12:00:00Z"},  # before start -> stop
    ]
    filtered, stop = fetcher._filter_by_date(
        results,
        start_date="2024-06-10T00:00:00Z",
        end_date="",
    )
    assert len(filtered) == 1
    assert filtered[0]["date"] == "2024-06-15T12:00:00Z"
    assert stop is True


def test_filter_by_date_excludes_after_end():
    """_filter_by_date excludes items with date after end_date."""
    results = [
        {"date": "2024-06-15T12:00:00Z"},
        {"date": "2024-06-20T12:00:00Z"},  # after end
        {"date": "2024-06-10T12:00:00Z"},
    ]
    end_date_str = "2024-06-15T23:59:59Z"
    filtered, stop = fetcher._filter_by_date(
        results,
        start_date="",
        end_date=end_date_str,
    )
    end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
    assert len(filtered) == 2
    for item in filtered:
        item_dt = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        assert item_dt <= end_dt
    assert stop is False


def test_filter_by_date_boundary_equal_to_start():
    """_filter_by_date includes item when date equals start_date."""
    results = [{"date": "2024-06-10T00:00:00Z"}]
    filtered, stop = fetcher._filter_by_date(
        results,
        start_date="2024-06-10T00:00:00Z",
        end_date="",
    )
    assert len(filtered) == 1
    assert stop is False


def test_filter_by_date_missing_date_in_item():
    """_filter_by_date handles items with missing or None date (no crash)."""
    results = [
        {"date": "2024-06-01T12:00:00Z"},
        {},  # no date
        {"date": None},
        {"subject": "no date"},
    ]
    filtered, _ = fetcher._filter_by_date(
        results,
        start_date="2024-05-01T00:00:00Z",
        end_date="2024-12-31T23:59:59Z",
    )
    # First item included; others have no date so skipped
    assert len(filtered) >= 1
    assert filtered[0]["date"] == "2024-06-01T12:00:00Z"


def test_filter_by_date_all_before_start():
    """_filter_by_date returns empty and stop=True when first item is before start."""
    results = [{"date": "2024-01-01T00:00:00Z"}]
    filtered, stop = fetcher._filter_by_date(
        results,
        start_date="2024-06-01T00:00:00Z",
        end_date="",
    )
    assert filtered == []
    assert stop is True


# --- format_email ---


def test_format_email_minimal_item():
    """format_email handles minimal item with only required keys."""
    item = {}
    source_url = (
        "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/"
    )
    out = fetcher.format_email(item, source_url)
    assert out["msg_id"] == ""
    assert out["parent_id"] == ""
    assert out["thread_id"] == ""
    assert out["subject"] == ""
    assert out["content"] == ""
    assert out["list_name"] == "boost@lists.boost.org"
    assert out["sent_at"] is None
    assert "sender_address" in out
    assert "sender_name" in out


def test_format_email_full_item():
    """format_email maps all fields from a full API-like item."""
    item = {
        "message_id_hash": "<msg-123@lists.boost.org>",
        "parent": "https://lists.boost.org/archives/api/thread/456/",
        "thread": "https://lists.boost.org/archives/api/thread/789/",
        "subject": "Test subject",
        "content": "Body",
        "date": "2024-06-15T12:00:00Z",
        "sender": {"address": "user (a) example.com", "other": "ignored"},
        "sender_name": "Test User",
    }
    source_url = (
        "https://lists.boost.org/archives/api/list/boost-users@lists.boost.org/emails/"
    )
    out = fetcher.format_email(item, source_url)
    assert out["msg_id"] == "<msg-123@lists.boost.org>"
    assert out["parent_id"] == "456"
    assert out["thread_id"] == "789"
    assert out["subject"] == "Test subject"
    assert out["content"] == "Body"
    assert out["list_name"] == "boost-users@lists.boost.org"
    assert out["sent_at"] == "2024-06-15T12:00:00Z"
    assert out["sender_address"] == "user@example.com"
    assert out["sender_name"] == "Test User"


def test_format_email_sender_none():
    """format_email handles missing or None sender."""
    item = {"message_id_hash": "<x@y>", "sender": None}
    source_url = (
        "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/"
    )
    out = fetcher.format_email(item, source_url)
    assert out["sender_address"] == ""
    assert out["sender_name"] == ""


def test_format_email_sender_missing_address():
    """format_email handles sender dict without address key."""
    item = {"message_id_hash": "<x@y>", "sender": {}}
    source_url = (
        "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/"
    )
    out = fetcher.format_email(item, source_url)
    assert out["sender_address"] == ""


def test_format_email_parent_thread_with_trailing_slash():
    """format_email extracts id from parent/thread URLs (segment before final empty)."""
    item = {
        "message_id_hash": "<id>",
        "parent": "https://example.com/thread/123/",
        "thread": "https://example.com/thread/456/",
    }
    source_url = (
        "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/"
    )
    out = fetcher.format_email(item, source_url)
    assert out["parent_id"] == "123"
    assert out["thread_id"] == "456"


def test_format_email_parent_thread_empty_string():
    """format_email handles empty parent/thread (split gives empty or single segment)."""
    item = {"message_id_hash": "<id>", "parent": "", "thread": ""}
    source_url = (
        "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/"
    )
    out = fetcher.format_email(item, source_url)
    assert out["parent_id"] == ""
    assert out["thread_id"] == ""


def test_format_email_list_name_from_url():
    """format_email derives list_name from source_url path (-3 segment)."""
    source_url = "https://lists.boost.org/archives/api/list/boost-announce@lists.boost.org/emails/"
    out = fetcher.format_email({"message_id_hash": "x"}, source_url)
    assert out["list_name"] == "boost-announce@lists.boost.org"


# --- _get_start_date_from_db ---


@pytest.mark.django_db
def test_get_start_date_from_db_empty_returns_empty_string():
    """_get_start_date_from_db returns empty string when no messages in DB."""
    result = fetcher._get_start_date_from_db()
    assert result == ""


@pytest.mark.django_db
def test_get_start_date_from_db_returns_iso_utc_format(
    mailing_list_profile,
    default_list_name,
):
    """_get_start_date_from_db returns ISO 8601 UTC format like 2025-11-13T05:25:55Z."""
    from boost_mailing_list_tracker import services

    dt = datetime(2025, 11, 13, 5, 25, 55, tzinfo=timezone.utc)
    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<start-date-test@example.com>",
        sent_at=dt,
        list_name=default_list_name,
    )
    result = fetcher._get_start_date_from_db()
    assert result == "2025-11-13T05:25:55Z"


@pytest.mark.django_db
def test_get_start_date_from_db_uses_latest_sent_at(
    mailing_list_profile,
    default_list_name,
):
    """_get_start_date_from_db returns the latest sent_at among all messages."""
    from boost_mailing_list_tracker import services

    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<older@example.com>",
        sent_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        list_name=default_list_name,
    )
    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<newer@example.com>",
        sent_at=datetime(2025, 6, 15, 14, 30, 0, tzinfo=timezone.utc),
        list_name=default_list_name,
    )
    result = fetcher._get_start_date_from_db()
    assert result == "2025-06-15T14:30:00Z"


@pytest.mark.django_db
def test_get_start_date_from_db_naive_datetime_assumed_utc(
    mailing_list_profile,
    default_list_name,
):
    """_get_start_date_from_db formats naive sent_at (no tz conversion)."""
    from boost_mailing_list_tracker import services

    # Django may store naive as-is; strftime still produces the digits
    dt_naive = datetime(2025, 3, 10, 12, 0, 0)  # no tzinfo
    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<naive@example.com>",
        sent_at=dt_naive,
        list_name=default_list_name,
    )
    result = fetcher._get_start_date_from_db()
    # Should be formatted; if DB stores naive, we get "2025-03-10T12:00:00Z"
    assert result.startswith("2025-03-10")
    assert "T" in result
    assert result.endswith("Z")


# --- fetch_email_list (integration with mock) ---


def test_fetch_email_list_returns_none_on_fetch_failure():
    """fetch_email_list returns None when _fetch_page returns None."""
    with patch.object(fetcher, "_fetch_page", return_value=None):
        result = fetcher.fetch_email_list(
            "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/",
            start_date="",
            end_date="",
        )
    assert result is None


def test_fetch_email_list_returns_none_when_no_results():
    """fetch_email_list returns None when API returns empty results."""
    with patch.object(
        fetcher, "_fetch_page", return_value={"results": [], "next": None}
    ):
        result = fetcher.fetch_email_list(
            "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/",
        )
    assert result is None


def test_fetch_email_list_returns_filtered_results():
    """fetch_email_list returns list from results and respects date filter."""
    with patch.object(
        fetcher,
        "_fetch_page",
        return_value={
            "results": [
                {"date": "2024-06-15T12:00:00Z", "url": "https://example.com/1"}
            ],
            "next": None,
        },
    ):
        result = fetcher.fetch_email_list(
            "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/",
            start_date="",
            end_date="2024-12-31T23:59:59Z",
        )
    assert result is not None
    assert len(result) == 1
    assert result[0]["date"] == "2024-06-15T12:00:00Z"
