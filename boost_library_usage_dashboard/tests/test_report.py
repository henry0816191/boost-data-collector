"""Tests for boost_library_usage_dashboard.report."""

from boost_library_usage_dashboard.report import write_summary_report
from boost_library_usage_dashboard.utils import _version_tuple


def test_version_tuple_handles_empty_and_non_numeric():
    assert _version_tuple("") == (0, 0, 0)
    assert _version_tuple("1.82.x") == (1, 82, 0)
    assert _version_tuple("release-2.1.9-extra") == (2, 1, 9)


def test_write_summary_report_generates_core_sections(tmp_path):
    report_path = tmp_path / "report.md"
    stats = {
        "total_repositories": 100,
        "affected_repositories": 40,
        "total_libraries": 10,
        "total_usage_records": 1234,
        "top_libraries": [
            {
                "name": "algorithm",
                "repo_count": 11,
                "total_usage": 111,
                "earliest_commit": "",
                "latest_commit": "",
            }
        ],
        "never_used_libraries": [
            {"name": "foo", "created_version": "", "last_updated_version": ""}
        ],
        "version_related_stats": {
            "distribution_by_version": [("1.54.0", "2014-01-01", 10, 5)],
            "distribution_by_year_version": {
                "1.52.0": {"2014": 2},  # should be filtered out (<1.53.0)
                "1.53.0": {"2014": 3},
                "1.54.0": {"2014": 5},
            },
        },
    }
    write_summary_report(report_path, stats, stars_min_threshold=10)
    content = report_path.read_text(encoding="utf-8")

    assert "# Boost Usage Analysis Report" in content
    assert "## Overview" in content
    assert "algorithm" in content
    assert "N/A" in content  # earliest/latest fallback
    assert "## Never Used Boost Libraries" in content
    assert "## Boost Version Distribution" in content
    assert "## Repository Counts by Year and Version" in content
    assert "1.52.0" not in content
    assert "1.53.0" in content
    assert "1.54.0" in content
