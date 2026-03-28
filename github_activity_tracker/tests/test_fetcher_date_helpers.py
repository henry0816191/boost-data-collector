"""Tests for fetcher date range helper functions."""

from datetime import datetime, timezone

from github_activity_tracker.fetcher import _make_aware, _in_date_range


def test_make_aware_converts_naive_to_utc():
    """_make_aware converts naive datetime to UTC-aware."""
    naive = datetime(2024, 1, 1, 12, 0, 0)
    result = _make_aware(naive)
    assert result.tzinfo == timezone.utc
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 1


def test_make_aware_preserves_aware_datetime():
    """_make_aware returns aware datetime as-is."""
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = _make_aware(aware)
    assert result is aware


def test_make_aware_preserves_non_utc_aware_datetime():
    """_make_aware returns non-UTC aware datetime as-is (does not convert to UTC)."""
    from datetime import timedelta

    # Create a datetime in UTC+5
    utc_plus_5 = timezone(timedelta(hours=5))
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=utc_plus_5)
    result = _make_aware(dt)

    # _make_aware returns aware datetimes as-is; it doesn't convert to UTC
    assert result is dt
    assert result.tzinfo == utc_plus_5


def test_in_date_range_returns_true_when_in_range():
    """_in_date_range returns True when dt is within [start_time, end_time]."""
    dt = datetime(2024, 1, 5, tzinfo=timezone.utc)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)

    assert _in_date_range(dt, start, end) is True


def test_in_date_range_returns_false_when_before_start():
    """_in_date_range returns False when dt is before start_time."""
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    start = datetime(2024, 1, 5, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)

    assert _in_date_range(dt, start, end) is False


def test_in_date_range_returns_false_when_after_end():
    """_in_date_range returns False when dt is after end_time."""
    dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)

    assert _in_date_range(dt, start, end) is False


def test_in_date_range_returns_true_when_no_start_time():
    """_in_date_range returns True when start_time is None (no lower bound)."""
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)

    assert _in_date_range(dt, None, end) is True


def test_in_date_range_returns_true_when_no_end_time():
    """_in_date_range returns True when end_time is None (no upper bound)."""
    dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    assert _in_date_range(dt, start, None) is True


def test_in_date_range_returns_true_when_no_bounds():
    """_in_date_range returns True when both start_time and end_time are None."""
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)

    assert _in_date_range(dt, None, None) is True


def test_in_date_range_handles_naive_start_and_end():
    """_in_date_range handles naive start_time and end_time by assuming UTC."""
    dt = datetime(2024, 1, 5, tzinfo=timezone.utc)
    start = datetime(2024, 1, 1)  # Naive
    end = datetime(2024, 1, 10)  # Naive

    assert _in_date_range(dt, start, end) is True


def test_in_date_range_inclusive_boundaries():
    """_in_date_range is inclusive on both boundaries."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 10, tzinfo=timezone.utc)

    # Exactly at start
    assert _in_date_range(start, start, end) is True
    # Exactly at end
    assert _in_date_range(end, start, end) is True
