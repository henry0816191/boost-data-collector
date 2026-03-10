from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from boost_library_usage_dashboard.utils import _version_tuple


def write_summary_report(
    report_path: Path,
    stats: dict[str, Any],
    stars_min_threshold: int = 10,
) -> None:
    report_lines = [
        "# Boost Usage Analysis Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Data Source and Date Range",
        "",
        f"**Important**: All statistics in this report are computed using repositories with **>{stars_min_threshold} stars** only.",
        "The data covers repositories from 2002 to present.",
        "",
        f"**Interpretation note**: If the counts for the most recent year and the latest Boost version look smaller than others, this is often expected because newer repositories/releases have had less time to accumulate **>{stars_min_threshold} stars**, so they are under-represented by this filter.",
        "",
        "## Overview",
        "",
        f"- **Total Repositories (>{stars_min_threshold} stars)**: {stats['total_repositories']:,}",
        f"- **Repositories Using System Boost**: {stats['affected_repositories']:,}",
        f"- **Total Boost Libraries**: {stats['total_libraries']:,}",
        f"- **Total Usage Records**: {stats['total_usage_records']:,}",
        "",
        "## Top Boost Libraries by Repository Count",
        "",
        "| Library | Repository Count | Usage Count | Earliest Commit | Latest Commit |",
        "|---------|------------------|-------------|-----------------|---------------|",
    ]

    for lib in stats.get("top_libraries", []):
        earliest = lib.get("earliest_commit", "") or "N/A"
        latest = lib.get("latest_commit", "") or "N/A"
        name = lib.get("name", "Unknown")
        repo_count = lib.get("repo_count", 0)
        total_usage = lib.get("total_usage", 0)
        report_lines.append(
            f"| {name} | {repo_count:,} | {total_usage:,} | {earliest} | {latest} |"
        )

    if stats.get("never_used_libraries"):
        report_lines.extend(
            [
                "",
                "## Never Used Boost Libraries",
                "",
                f"This section lists Boost libraries that have **never been used** in any repository (>{stars_min_threshold} stars) in the dataset.",
                "",
                "| Library | Created Version | Last Updated Version |",
                "|---------|-----------------|----------------------|",
            ]
        )
        for lib in stats["never_used_libraries"]:
            name = lib.get("name", "Unknown")
            report_lines.append(
                f"| {name} | {lib.get('created_version') or 'N/A'} | {lib.get('last_updated_version') or 'N/A'} |"
            )

    version_stats = stats.get("version_related_stats", {})
    if version_stats.get("distribution_by_version"):
        report_lines.extend(
            [
                "",
                "## Boost Version Distribution",
                "",
                "| Version | Created at | Confirmed repository count | No confirmed repository count |",
                "|---------|----------------------------|------------------------------|------------------------------|",
            ]
        )
        for version, created_at, confirmed_count, no_confirmed_count in version_stats[
            "distribution_by_version"
        ]:
            report_lines.append(
                f"| {version} | {created_at} | {confirmed_count:,} | {no_confirmed_count:,} |"
            )

    if version_stats.get("distribution_by_year_version"):
        by_year_version = version_stats["distribution_by_year_version"]
        versions = [
            v
            for v in by_year_version.keys()
            if v and _version_tuple(v) >= _version_tuple("1.53.0")
        ]
        versions = sorted(versions, key=_version_tuple, reverse=True)
        all_years = sorted(
            {
                year
                for version in versions
                for year in by_year_version.get(version, {}).keys()
            },
            reverse=True,
        )
        report_lines.extend(
            [
                "",
                "## Repository Counts by Year and Version",
                "",
            ]
        )
        header = "| Year |" + "".join(f" {version} |" for version in versions)
        sep = "|------|" + "".join("--------|" for _ in versions)
        report_lines.extend([header, sep])
        for year in all_years:
            row = f"| {year} |"
            for version in versions:
                count = by_year_version.get(version, {}).get(year, 0)
                row += f" {count:,} |" if count > 0 else " |"
            report_lines.append(row)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
