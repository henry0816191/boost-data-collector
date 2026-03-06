"""Metrics helpers for Boost usage dashboard analyzer."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from django.db.models import Avg, Count, Max, Min

from .models import BoostUsage


def calculate_library_metrics_by_file_usage(
    analyzer: Any,
    recent_years: int = 5,
) -> dict[str, dict[str, Any]]:
    """Aggregate per-library usage trends from file-level BoostUsage rows."""
    current_year = datetime.now().year - 1
    recent_year_threshold = current_year - recent_years + 1
    rows = (
        BoostUsage.objects.select_related(  # pylint: disable=no-member
            "boost_header__library",
            "boost_header__github_file",
            "repo__githubrepository_ptr",
            "repo__githubrepository_ptr__owner_account",
        )
        .filter(
            excepted_at__isnull=True,
            boost_header__isnull=False,
            repo__githubrepository_ptr__stars__gte=analyzer.stars_min_threshold,
        )
        .iterator()
    )

    library_year_data: dict[str, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"created_count": 0, "last_commit_count": 0})
    )
    library_top_repo: dict[str, dict[str, int]] = defaultdict(dict)
    library_headers: dict[str, dict[str, int]] = defaultdict(dict)

    for usage in rows:
        library_name = usage.boost_header.library.name
        repo = usage.repo.githubrepository_ptr
        owner = repo.owner_account.username or ""
        repo_name = f"{owner}/{repo.repo_name}" if owner else repo.repo_name
        usage_count = 1
        header_name = usage.boost_header.github_file.filename

        if repo.repo_created_at:
            year = repo.repo_created_at.year
            library_year_data[library_name][year]["created_count"] += usage_count
        if usage.last_commit_date:
            year = usage.last_commit_date.year
            library_year_data[library_name][year]["last_commit_count"] += usage_count

        library_headers[library_name][header_name] = (
            library_headers[library_name].get(header_name, 0) + usage_count
        )
        library_top_repo[library_name][repo_name] = (
            library_top_repo[library_name].get(repo_name, 0) + usage_count
        )

    metrics: dict[str, dict[str, Any]] = {}
    for library_name, year_map in library_year_data.items():
        year_data = sorted(year_map.items(), key=lambda x: x[0])
        computed = calculate_trend_metrics(year_data, recent_year_threshold)
        sorted_headers = sorted(
            library_headers.get(library_name, {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )
        metrics[library_name] = {
            "total_usage": computed["total_usage"],
            "recent_usage": computed["recent_usage"],
            "past_usage": computed["past_usage"],
            "activity_score": computed["activity_score"],
            "year_data": {str(year): data for year, data in year_data},
            "top_repo_list": library_top_repo.get(library_name, {}),
            "used_headers": {name: count for name, count in sorted_headers},
        }
    return metrics


def calculate_trend_metrics(
    year_data: list[tuple[int, dict[str, int]]],
    recent_year_threshold: int,
) -> dict[str, float]:
    """Compute activity score using derivative/trend/momentum blend."""
    if not year_data:
        return {
            "total_usage": 0,
            "activity_score": -10.0,
            "recent_usage": 0,
            "past_usage": 0,
        }

    current_year = datetime.now().year
    # Exclude only the in-progress current year when present.
    to_last_year_data = [(y, v) for y, v in year_data if y < current_year]
    if not to_last_year_data:
        to_last_year_data = year_data
    recent_usage = sum(
        v["created_count"] for y, v in to_last_year_data if y >= recent_year_threshold
    )
    past_usage = sum(
        v["created_count"] for y, v in to_last_year_data if y < recent_year_threshold
    )
    total_usage = recent_usage + past_usage
    if total_usage == 0:
        return {
            "total_usage": 0,
            "activity_score": -10.0,
            "recent_usage": 0,
            "past_usage": 0,
        }

    years = [y for y, _ in to_last_year_data]
    counts = [v["created_count"] for _, v in to_last_year_data]
    ratios = [count / total_usage for count in counts]
    x_values = [year - recent_year_threshold for year in years]

    derivation = 0.0
    for idx in range(1, len(x_values)):
        dx = x_values[idx] - x_values[idx - 1]
        if dx:
            derivation += ((ratios[idx] - ratios[idx - 1]) / dx) * idx
    derivation_score = derivation * math.log(total_usage + 1, 10)

    n = len(x_values)
    trend_score = 0.0
    if n >= 2:
        sum_x = sum(x_values)
        sum_y = sum(ratios)
        sum_xy = sum(x * y for x, y in zip(x_values, ratios, strict=True))
        sum_x2 = sum(x * x for x in x_values)
        denom = n * sum_x2 - sum_x * sum_x
        if denom:
            slope = (n * sum_xy - sum_x * sum_y) / denom
            avg_usage = sum_y / n if n else 1
            trend_score = slope / (avg_usage + 1) * math.log(total_usage + 1, 10)

    momentum_score = 0.0
    if len(counts) >= 2:
        momentum = 0.0
        total_weight = 0.0
        for idx in range(1, len(counts)):
            weight = math.exp((idx - len(counts)) * 0.3)
            change = (ratios[idx] - ratios[idx - 1]) / (ratios[idx - 1] + 1)
            momentum += change * weight
            total_weight += weight
        if total_weight:
            momentum_score = (momentum / total_weight) * math.log(total_usage + 1, 10)

    return {
        "total_usage": total_usage,
        "activity_score": derivation_score * 0.4
        + trend_score * 0.3
        + momentum_score * 0.3,
        "recent_usage": recent_usage,
        "past_usage": past_usage,
    }


def calculate_library_metrics_by_repository(analyzer: Any) -> dict[str, dict[str, Any]]:
    """Aggregate per-library repository-level metrics."""
    rows = (
        BoostUsage.objects.filter(  # pylint: disable=no-member
            excepted_at__isnull=True,
            boost_header__isnull=False,
            repo__githubrepository_ptr__stars__gte=analyzer.stars_min_threshold,
        )
        .values("boost_header__library__name")
        .annotate(
            repo_count=Count("repo_id", distinct=True),
            earliest_commit=Min("last_commit_date"),
            latest_commit=Max("last_commit_date"),
            average_stars=Avg("repo__githubrepository_ptr__stars"),
        )
    )
    metrics: dict[str, dict[str, Any]] = {}
    for row in rows:
        metrics[row["boost_header__library__name"]] = {
            "repo_count": row["repo_count"],
            "earliest_commit": (
                row["earliest_commit"].strftime("%Y-%m-%d %H:%M:%S")
                if row["earliest_commit"]
                else ""
            ),
            "latest_commit": (
                row["latest_commit"].strftime("%Y-%m-%d %H:%M:%S")
                if row["latest_commit"]
                else ""
            ),
            "average_stars": int(row["average_stars"] or 0),
        }
    return metrics
