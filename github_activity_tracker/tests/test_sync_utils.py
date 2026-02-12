"""Tests for github_activity_tracker.sync utils (parse_github_user, parse_datetime)."""
import pytest
from datetime import datetime, timezone
from github_activity_tracker.sync.utils import parse_github_user, parse_datetime


def test_parse_github_user_none():
    """parse_github_user(None) returns empty-style dict."""
    out = parse_github_user(None)
    assert out["account_id"] is None
    assert out["username"] == ""
    assert out["display_name"] == ""
    assert out["avatar_url"] == ""


def test_parse_github_user_full():
    """parse_github_user with full dict returns correct fields."""
    user = {
        "id": 42,
        "login": "joe",
        "name": "Joe Dev",
        "avatar_url": "https://example.com/avatar.png",
    }
    out = parse_github_user(user)
    assert out["account_id"] == 42
    assert out["username"] == "joe"
    assert out["display_name"] == "Joe Dev"
    assert out["avatar_url"] == "https://example.com/avatar.png"


def test_parse_github_user_partial():
    """parse_github_user with missing keys uses empty string."""
    out = parse_github_user({"id": 1})
    assert out["account_id"] == 1
    assert out["username"] == ""
    assert out["display_name"] == ""
    assert out["avatar_url"] == ""


def test_parse_datetime_none():
    """parse_datetime(None) returns None."""
    assert parse_datetime(None) is None


def test_parse_datetime_empty():
    """parse_datetime('') returns None."""
    assert parse_datetime("") is None


def test_parse_datetime_iso():
    """parse_datetime parses ISO format with Z and returns timezone-aware UTC."""
    result = parse_datetime("2024-01-15T10:30:00Z")
    assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_datetime_invalid_returns_none():
    """parse_datetime with invalid string returns None."""
    assert parse_datetime("not-a-date") is None


@pytest.mark.parametrize("date_str,expected_year", [
    ("2023-06-01T00:00:00Z", 2023),
    ("2025-12-31T23:59:59Z", 2025),
])
def test_parse_datetime_parametrized(date_str, expected_year):
    """Parametrized: parse_datetime returns correct year."""
    result = parse_datetime(date_str)
    assert result is not None
    assert result.year == expected_year
