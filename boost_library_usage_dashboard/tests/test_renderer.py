"""Tests for boost_library_usage_dashboard.renderer and dashboard_html."""

import json

import pytest

from boost_library_usage_dashboard.dashboard_html import generate_dashboard_html
from boost_library_usage_dashboard.renderer import render_dashboard_html


def _minimal_dashboard_data() -> dict:
    return {
        "repos_by_year": {"2023": 10, "2024": 15},
        "repos_by_version": [("1.81.0", 5), ("1.84.0", 20)],
        "repos_by_year_boost_rate": [
            {
                "year": "2024",
                "cpp_repo_count": 100,
                "over_10": 50,
                "boost_over_10_percentage": "30.00%",
            },
        ],
        "language_comparison_data": {},
        "metrics_by_library": [
            {
                "name": "asio",
                "repo_count": 100,
                "total_usage": 500,
                "activity_score": 1.5,
            },
            {
                "name": "filesystem",
                "repo_count": 80,
                "total_usage": 300,
                "activity_score": 0.8,
            },
        ],
        "top_repositories": {
            "top20_by_stars": [
                {"repo_name": "org/repo1", "stars": 1000, "usage_count": 10}
            ],
            "top20_by_usage": [],
            "top20_by_created": [],
        },
        "libraries_page_data": {
            "asio": {
                "over_view": {
                    "created_version": "1.70.0",
                    "last_updated_version": "1.84.0",
                    "used_repo_count": 100,
                    "average_star": 50,
                    "active_score": 1.5,
                    "description": "Async I/O.",
                },
                "external_consumers": {
                    "table_data": [
                        {
                            "name": "org/repo1",
                            "stars": 100,
                            "usage_count": 5,
                            "created_at": "2024-01-01",
                        }
                    ],
                },
                "contribute_data": {"table_data": []},
                "internal_dependents_data": {
                    "table_data": [{"name": "other", "depth": 1}]
                },
            },
        },
        "all_versions_for_chart": ["1.81.0", "1.84.0"],
    }


def test_generate_dashboard_html_creates_index_and_libraries(tmp_path):
    """generate_dashboard_html writes index.html and library pages from JSON."""
    data_file = tmp_path / "dashboard_data.json"
    data_file.write_text(
        json.dumps(_minimal_dashboard_data(), indent=2), encoding="utf-8"
    )

    generate_dashboard_html(
        dashboard_data_file=data_file,
        output_dir=tmp_path,
        libraries_dir=tmp_path / "libraries",
    )

    assert (tmp_path / "index.html").is_file()
    content = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Boost Library Usage Dashboard" in content
    assert "New Repositories Using Boost Libraries by Year" in content
    assert "libraries/asio.html" in content

    assert (tmp_path / "libraries").is_dir()
    assert (tmp_path / "libraries" / "asio.html").is_file()
    lib_content = (tmp_path / "libraries" / "asio.html").read_text(encoding="utf-8")
    assert "asio" in lib_content
    assert "1.70.0" in lib_content
    assert "org/repo1" in lib_content
    assert "Back to Dashboard" in lib_content


def test_generate_dashboard_html_raises_when_data_file_missing(tmp_path):
    """generate_dashboard_html raises FileNotFoundError when JSON file is missing."""
    with pytest.raises(FileNotFoundError, match="not found"):
        generate_dashboard_html(
            dashboard_data_file=tmp_path / "nonexistent.json",
            output_dir=tmp_path,
        )


def test_render_dashboard_html_calls_generate(tmp_path):
    """render_dashboard_html uses dashboard_data.json in output_dir and writes HTML."""
    data_file = tmp_path / "dashboard_data.json"
    data_file.write_text(
        json.dumps(_minimal_dashboard_data(), indent=2), encoding="utf-8"
    )

    render_dashboard_html(base_dir=tmp_path / "ignored", output_dir=tmp_path)

    assert (tmp_path / "index.html").is_file()
    assert (tmp_path / "libraries" / "asio.html").is_file()
