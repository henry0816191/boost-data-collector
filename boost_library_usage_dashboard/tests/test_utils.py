"""Tests for boost_library_usage_dashboard.utils."""

from boost_library_usage_dashboard.utils import (
    format_percent,
    get_year_repositories_from_md,
    normalize_version_str,
)


def test_normalize_version_str_two_segments():
    assert normalize_version_str("1.82") == "1.82.0"


def test_normalize_version_str_rejects_zero_prefix():
    assert normalize_version_str("0.99") is None


def test_format_percent():
    assert format_percent(1, 4) == "25.00%"
    assert format_percent(0, 0) == "0.00%"


def test_get_year_repositories_from_md_parses_language_sections(tmp_path):
    md = tmp_path / "language_repo_count_report.md"
    md.write_text(
        "\n".join(
            [
                "## C++",
                "",
                "| Year | All Repos | Repos with 10+ Stars |",
                "|------|-----------|----------------------|",
                "| 2020 | 1,200 | 130 |",
                "| 2021 | 2,300 | 260 |",
                "",
                "## Python",
                "",
                "| Year | All Repos | Repos with 10+ Stars |",
                "|------|-----------|----------------------|",
                "| 2020 | 3,000 | 500 |",
                "",
                "## Summary (All Languages Combined)",
            ]
        ),
        encoding="utf-8",
    )
    data = get_year_repositories_from_md(md)
    assert data["C++"]["2020"]["all"] == 1200
    assert data["C++"]["2020"]["stars_10_plus"] == 130
    assert data["Python"]["2020"]["all"] == 3000

