"""Output assembly helpers for Boost usage dashboard analyzer."""

from __future__ import annotations

import json
import logging
from typing import Any

from .analyzer_libraries import collect_libraries_page_data
from .utils import _version_tuple

logger = logging.getLogger(__name__)


def _created_at_key(created_at: str) -> tuple[int, str]:
    """Sort by version created date; unknown dates go last."""
    value = str(created_at or "").strip()
    return (1, "") if not value else (0, value)


def collect_top_repositories_for_dashboard(
    repo_info: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return top repositories by stars/usage/created date."""

    def _numeric_key(row: dict[str, Any], feature: str) -> int:
        value = row.get(feature)
        if isinstance(value, (int, float)):
            return int(value)
        if value in (None, ""):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def get_top(feature: str) -> list[dict[str, Any]]:
        if feature in {"stars", "usage_count"}:
            return sorted(
                repo_info,
                key=lambda row: _numeric_key(row, feature),
                reverse=True,
            )[:20]
        return sorted(
            repo_info,
            key=lambda row: str(row.get(feature) or ""),
            reverse=True,
        )[:20]

    return {
        "top20_by_stars": get_top("stars"),
        "top20_by_usage": get_top("usage_count"),
        "top20_by_created": get_top("created_at"),
    }


def collect_dashboard_data(analyzer: Any, stats: dict[str, Any]) -> None:
    """Build and persist dashboard_data.json file."""
    dashboard_data: dict[str, Any] = {}
    dashboard_data["repos_by_year"] = stats["repos_by_year"]
    version_counts = stats["version_related_stats"]["distribution_by_version"]
    min_chart_version = "1.34.0"
    repos_by_version_rows: list[tuple[str, str, int]] = []
    min_key = _version_tuple(min_chart_version)
    for row in version_counts:
        if isinstance(row, dict):
            version = str(row.get("version", row.get(0, "")) or "")
            created_at = str(row.get("created_at", row.get(1, "")) or "")
            confirmed = int(row.get("confirmed", row.get(2, 0)) or 0)
            guessed = int(row.get("guessed", row.get(3, 0)) or 0)
        elif isinstance(row, (list, tuple)) and len(row) >= 4:
            version = str(row[0] or "")
            created_at = str(row[1] or "")
            confirmed = int(row[2] or 0)
            guessed = int(row[3] or 0)
        else:
            logger.debug(
                "Skipping malformed version row (expected dict or sequence of length >= 4): %s",
                row,
            )
            continue
        if _version_tuple(version) >= min_key:
            repos_by_version_rows.append((version, created_at, confirmed + guessed))

    repos_by_version_rows.sort(
        key=lambda x: (_created_at_key(x[1]), _version_tuple(x[0]))
    )
    dashboard_data["repos_by_version"] = [
        (version, count) for version, _, count in repos_by_version_rows
    ]
    dashboard_data["repos_by_year_boost_rate"] = stats["repos_by_year_boost_rate"]
    dashboard_data["language_comparison_data"] = stats["language_comparison_data"]
    dashboard_data["metrics_by_library"] = analyzer.filter_and_sort_libraries(
        fields=[
            "name",
            "created_version",
            "removed_version",
            "total_usage",
            "recent_usage",
            "past_usage",
            "activity_score",
            "repo_count",
            "earliest_commit",
            "latest_commit",
            "average_stars",
        ]
    )
    dashboard_data["top_repositories"] = collect_top_repositories_for_dashboard(
        analyzer.repo_info
    )
    dashboard_data["libraries_page_data"] = collect_libraries_page_data(analyzer)
    dashboard_data["all_versions_for_chart"] = analyzer.version_name_list

    analyzer.output_dir.mkdir(parents=True, exist_ok=True)
    analyzer.dashboard_data_file.write_text(
        json.dumps(dashboard_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
