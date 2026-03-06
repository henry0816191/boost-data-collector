"""Tests for boost_library_usage_dashboard.utils."""

from boost_library_usage_dashboard.utils import (
    format_percent,
    normalize_version_str,
    sanitize_library_name,
)


def test_normalize_version_str_two_segments():
    assert normalize_version_str("1.82") == "1.82.0"


def test_normalize_version_str_rejects_zero_prefix():
    assert normalize_version_str("0.99") is None


def test_format_percent():
    assert format_percent(1, 4) == "25.00%"
    assert format_percent(0, 0) == "0.00%"


def test_sanitize_library_name_replaces_irregular_chars():
    assert sanitize_library_name("asio/io") == "asio_io"
