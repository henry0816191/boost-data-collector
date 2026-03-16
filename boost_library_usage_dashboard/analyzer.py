from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from django.apps import apps
from django.db.models import Count, Min

from boost_library_tracker.models import BoostLibrary, BoostLibraryVersion, BoostVersion
from boost_usage_tracker.models import BoostExternalRepository, BoostUsage

from .analyzer_libraries import (
    build_library_overview_data,
    collect_commit_info_by_library,
    collect_dependents_data,
    collect_libraries_page_data,
    find_all_transitive_dependencies,
    get_contribution_data,
    get_external_consumer_data,
    get_first_version_released_after,
    get_last_updated_version,
)
from .analyzer_metrics import (
    calculate_library_metrics_by_file_usage,
    calculate_library_metrics_by_repository,
    calculate_trend_metrics,
)
from .analyzer_output import (
    collect_dashboard_data,
    collect_top_repositories_for_dashboard,
)
from .utils import format_percent

logger = logging.getLogger(__name__)

STARS_MIN_THRESHOLD = 10


class BoostUsageDashboardAnalyzer:
    def __init__(self, base_dir: Path, output_dir: Path):
        self.base_dir = base_dir
        self.output_dir = output_dir
        self.dashboard_data_file = output_dir / "dashboard_data.json"
        self.report_file = output_dir / "Boost_Usage_Report_total.md"
        self.stars_min_threshold = STARS_MIN_THRESHOLD

        self.version_info = list(
            BoostVersion.objects.filter(version__regex=r"^boost-\d+\.\d+\.0$").order_by(
                "version"
            )
        )  # pylint: disable=no-member
        self.version_name_list = [
            v.version.replace("boost-", "") for v in self.version_info
        ]
        self.version_by_id = {v.id: v for v in self.version_info}

        self.repo_info: list[dict[str, Any]] = []
        self.repo_info_dict: dict[str, dict[str, Any]] = {}
        self.library_info: list[dict[str, Any]] = []

    def run(self) -> dict[str, Any]:
        self._load_repository_info()
        self._load_library_info()
        stats = self.generate_statistics()
        self._collect_dashboard_data(stats)
        return stats

    def _load_repository_info(self) -> None:
        usage_counts = {
            row["repo_id"]: row["usage_count"]
            for row in BoostUsage.objects.filter(  # pylint: disable=no-member
                excepted_at__isnull=True,
                repo__is_boost_used=True,
                repo__githubrepository_ptr__stars__gt=self.stars_min_threshold,
            )
            .values("repo_id")
            .annotate(usage_count=Count("id"))
        }

        repos = (
            BoostExternalRepository.objects.select_related(  # pylint: disable=no-member
                "githubrepository_ptr",
                "githubrepository_ptr__owner_account",
            )
            .filter(
                is_boost_used=True,
                githubrepository_ptr__stars__gt=self.stars_min_threshold,
            )
            .order_by("githubrepository_ptr__id")
        )
        for ext_repo in repos:
            repo = ext_repo.githubrepository_ptr
            owner = repo.owner_account.username or ""
            full_name = f"{owner}/{repo.repo_name}" if owner else repo.repo_name
            row = {
                "id": repo.id,
                "repo_name": full_name,
                "affect_from_boost": bool(ext_repo.is_boost_used),
                "stars": repo.stars or 0,
                "created_at": (
                    repo.repo_created_at.isoformat() if repo.repo_created_at else ""
                ),
                "pushed_at": (
                    repo.repo_pushed_at.isoformat() if repo.repo_pushed_at else ""
                ),
                "boost_version": ext_repo.boost_version or "",
                "candidate_version": "",
                "usage_count": usage_counts.get(ext_repo.pk, 0),
            }
            if not row["boost_version"] and repo.repo_created_at:
                row["candidate_version"] = self.get_candidate_version_from_created_at(
                    repo.repo_created_at
                )
            self.repo_info.append(row)
            self.repo_info_dict[full_name] = row

    def _load_library_info(self) -> None:
        by_file_usage = self._calculate_library_metrics_by_file_usage(recent_years=5)
        by_repository = self._calculate_library_metrics_by_repository()

        # libs = BoostLibrary.objects.select_related("repo").all().order_by("name")  # pylint: disable=no-member

        latest_version_id = self.version_info[-1].id if self.version_info else None
        libs_qs = BoostLibrary.objects.select_related(
            "repo"
        )  # pylint: disable=no-member
        if latest_version_id is not None:
            libs_qs = libs_qs.filter(library_versions__version_id=latest_version_id)
        else:
            libs_qs = libs_qs.none()
        libs = libs_qs.distinct().order_by("name")
        logger.debug(
            f"Loaded {len(libs)} libraries. Latest version: {latest_version_id}"
        )
        created_versions = {
            row["library_id"]: row["version__version"]
            for row in BoostLibraryVersion.objects.values(
                "library_id"
            ).annotate(  # pylint: disable=no-member
                version__version=Min("version__version")
            )
        }
        desc_map: dict[int, str] = {}
        for row in (
            BoostLibraryVersion.objects.exclude(
                description=""
            )  # pylint: disable=no-member
            .values("library_id", "description", "version__version")
            .order_by("library_id", "-version__version")
        ):
            desc_map.setdefault(row["library_id"], row["description"])

        for lib in libs:
            lib_data: dict[str, Any] = {
                "id": lib.id,
                "name": lib.name,
                "created_version": created_versions.get(lib.id, ""),
                "last_updated_version": "",
                "removed_version": "",
                "total_usage": 0,
                "recent_usage": 0,
                "past_usage": 0,
                "activity_score": -10.0,
                "average_stars": 0,
                "year_data": {},
                "top_repo_list": {},
                "repo_count": 0,
                "earliest_commit": "",
                "latest_commit": "",
                "description": desc_map.get(lib.id, ""),
                "used_headers": {},
            }
            lib_data.update(by_file_usage.get(lib.name, {}))
            lib_data.update(by_repository.get(lib.name, {}))
            self.library_info.append(lib_data)

        # contribution mapping depends on self.library_info names.
        contribute_data = self._collect_commit_info_by_library()
        for lib_data in self.library_info:
            lib_data["contribute_data"] = contribute_data.get(lib_data["name"], {})

    def generate_statistics(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        total_repositories = len(self.repo_info)
        affected_repositories = sum(
            1 for repo in self.repo_info if repo["affect_from_boost"]
        )
        stats.update(
            {
                "total_repositories": total_repositories,
                "affected_repositories": affected_repositories,
                "total_usage_records": sum(
                    repo["usage_count"] for repo in self.repo_info
                ),
                "total_libraries": len(self.library_info),
            }
        )

        stats["version_related_stats"] = self.get_version_distribution()
        stats["top_libraries"] = self.filter_and_sort_libraries(
            fields=[
                "name",
                "repo_count",
                "total_usage",
                "earliest_commit",
                "latest_commit",
            ],
            sort_field="repo_count",
            sort_order="DESC",
            limit=20,
        )
        stats["never_used_libraries"] = self.filter_and_sort_libraries(
            fields=["name", "created_version", "last_updated_version"],
            sort_field="created_version",
            sort_order="ASC",
            condition_field="repo_count",
            condition_value=0,
            condition_signal=0,
        )
        stats["top_active_libraries"] = self.filter_and_sort_libraries(
            fields=[
                "name",
                "total_usage",
                "recent_usage",
                "past_usage",
                "activity_score",
            ],
            sort_field="activity_score",
            sort_order="DESC",
            limit=20,
        )
        stats["bottom_active_libraries"] = self.filter_and_sort_libraries(
            fields=[
                "name",
                "total_usage",
                "recent_usage",
                "past_usage",
                "activity_score",
            ],
            sort_field="activity_score",
            sort_order="ASC",
            limit=20,
            condition_field="activity_score",
            condition_value=-10,
            condition_signal=1,
        )
        stats["repos_by_year"] = self._get_repository_count_by_year("created_at")
        stats.update(self._load_repository_count_from_db(stats["repos_by_year"]))
        return stats

    def get_candidate_version_from_created_at(self, created_at: datetime) -> str:
        candidate_version = ""
        candidate_dt = None
        for version in self.version_info:
            if not version.version_created_at:
                continue
            if version.version_created_at <= created_at:
                if candidate_dt is None or version.version_created_at > candidate_dt:
                    candidate_dt = version.version_created_at
                    candidate_version = version.version
        return candidate_version

    def get_version_distribution(self) -> dict[str, Any]:
        version_year_counts: dict[str, dict[str, int]] = {}
        confirmed: dict[str, int] = {}
        guessed: dict[str, int] = {}
        no_version_count = 0
        total_repositories = len(self.repo_info)

        for repo in self.repo_info:
            version_name = repo.get("boost_version", "")
            year = (repo.get("created_at") or "")[:4]
            if version_name not in version_year_counts:
                version_year_counts[version_name] = {}
            if year:
                version_year_counts[version_name][year] = (
                    version_year_counts[version_name].get(year, 0) + 1
                )
            if version_name:
                confirmed[version_name] = confirmed.get(version_name, 0) + 1
                continue
            no_version_count += 1
            candidate = repo.get("candidate_version", "")
            guessed[candidate] = guessed.get(candidate, 0) + 1

        distribution = []
        for version in self.version_info:
            created = (
                version.version_created_at.strftime("%Y-%m-%d")
                if version.version_created_at
                else ""
            )
            distribution.append(
                (
                    version.version,
                    created,
                    confirmed.get(version.version, 0),
                    guessed.get(version.version, 0),
                )
            )

        return {
            "repos_with_version": total_repositories - no_version_count,
            "repos_without_version": no_version_count,
            "version_coverage_percent": (
                ((total_repositories - no_version_count) / total_repositories * 100)
                if total_repositories
                else 0
            ),
            "distribution_by_version": distribution,
            "distribution_by_year_version": version_year_counts,
        }

    def _get_repository_count_by_year(self, time_field: str) -> dict[str, int]:
        repos_by_year: dict[str, int] = {}
        for repo in self.repo_info:
            year = (repo.get(time_field, "") or "")[:4]
            if year and repo.get("affect_from_boost"):
                repos_by_year[year] = repos_by_year.get(year, 0) + 1
        return repos_by_year

    def _calculate_library_metrics_by_file_usage(
        self, recent_years: int = 5
    ) -> dict[str, dict[str, Any]]:
        return calculate_library_metrics_by_file_usage(self, recent_years)

    def calculate_trend_metrics(
        self,
        year_data: list[tuple[int, dict[str, int]]],
        recent_year_threshold: int,
    ) -> dict[str, float]:
        return calculate_trend_metrics(year_data, recent_year_threshold)

    def _calculate_library_metrics_by_repository(self) -> dict[str, dict[str, Any]]:
        return calculate_library_metrics_by_repository(self)

    def _load_repository_count_from_db(
        self, boost_repos_by_year: dict[str, int]
    ) -> dict[str, Any]:
        """
        Load language/year repository counts from CreatedReposByLanguage table.

        Uses dynamic model lookup so this analyzer remains import-safe on branches
        where the CreatedReposByLanguage model is not merged yet.
        """
        try:
            CreatedReposByLanguage = apps.get_model(  # noqa: N806
                "github_activity_tracker",
                "CreatedReposByLanguage",
            )
        except LookupError:
            logger.warning(
                "CreatedReposByLanguage model not available; skipping language comparison data."
            )
            return {"repos_by_year_boost_rate": [], "language_comparison_data": {}}

        language_data: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
        rows = (
            CreatedReposByLanguage.objects.select_related(
                "language"
            )  # pylint: disable=no-member
            .all()
            .order_by("language__name", "year")
        )
        for row in rows:
            language_name = row.language.name
            year_key = str(row.year)
            language_data[language_name][year_key] = {
                "all": int(row.all_repos or 0),
                "stars_10_plus": int(row.significant_repos or 0),
            }

        cpp_data = language_data.get("C++", {})
        repo_data = []
        for year, data in cpp_data.items():
            cpp_repo_count = data["all"]
            over_10 = data["stars_10_plus"]
            boost_over_10 = boost_repos_by_year.get(year, 0)
            repo_data.append(
                {
                    "year": year,
                    "cpp_repo_count": int(cpp_repo_count),
                    "over_10": over_10,
                    "boost_over_10": boost_over_10,
                    "boost_over_10_percentage": format_percent(boost_over_10, over_10),
                }
            )
        repo_data.sort(key=lambda x: x["year"], reverse=True)
        return {
            "repos_by_year_boost_rate": repo_data,
            "language_comparison_data": dict(language_data),
        }

    def filter_and_sort_libraries(
        self,
        fields: list[str] | None = None,
        sort_field: str = "name",
        sort_order: str = "asc",
        condition_field: str | None = None,
        condition_value: int = 0,
        condition_signal: int = 1,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        ret_data = self.library_info.copy()
        fields = list(fields or [])
        if condition_field and condition_field not in fields:
            fields.append(condition_field)
        if sort_field and sort_field not in fields:
            fields.append(sort_field)
        if fields:
            ret_data = [{field: lib.get(field) for field in fields} for lib in ret_data]
        if sort_field:
            ret_data.sort(
                key=lambda x: x.get(sort_field) or 0,
                reverse=sort_order.lower() == "desc",
            )
        if condition_field:
            if condition_signal > 0:
                ret_data = [
                    lib
                    for lib in ret_data
                    if (lib.get(condition_field) or 0) > condition_value
                ]
            elif condition_signal < 0:
                ret_data = [
                    lib
                    for lib in ret_data
                    if (lib.get(condition_field) or 0) < condition_value
                ]
            else:
                ret_data = [
                    lib
                    for lib in ret_data
                    if (lib.get(condition_field) or 0) == condition_value
                ]
        if limit:
            ret_data = ret_data[:limit]
        return ret_data

    def _collect_top_repositories_for_dashboard(self) -> dict[str, Any]:
        return collect_top_repositories_for_dashboard(self.repo_info)

    def _collect_dependents_data(self) -> dict[int, dict[str, Any]]:
        return collect_dependents_data(self)

    def _find_all_transitive_dependencies(
        self,
        main_lib_id: int,
        version_id: int,
        graph: dict[int, dict[int, list[int]]],
    ) -> dict[int, int]:
        return find_all_transitive_dependencies(main_lib_id, version_id, graph)

    def _collect_commit_info_by_library(self) -> dict[str, Any]:
        return collect_commit_info_by_library(self)

    def _get_first_version_released_after(
        self, commit_at: datetime | None
    ) -> str | None:
        return get_first_version_released_after(self.version_info, commit_at)

    def _normalize_and_moving_version(
        self, version: str, forward_step: int = 0
    ) -> str | None:
        if not version:
            return None
        if version not in self.version_name_list:
            return version
        current_id = self.version_name_list.index(version)
        new_id = current_id + forward_step
        if new_id < 0 or new_id >= len(self.version_name_list):
            return None
        return self.version_name_list[new_id]

    def _get_external_consumer_data(self, lib: dict[str, Any]) -> dict[str, Any]:
        return get_external_consumer_data(lib, self.repo_info_dict)

    def _get_contribution_data(self, lib: dict[str, Any]) -> dict[str, Any]:
        return get_contribution_data(lib)

    def _get_last_updated_version(self, contribute_data: dict[str, Any]) -> str:
        return get_last_updated_version(contribute_data)

    def _build_library_overview_data(
        self, lib_source: dict[str, Any], lib_data: dict[str, Any]
    ) -> dict[str, Any]:
        return build_library_overview_data(lib_source, lib_data)

    def _collect_libraries_page_data(self) -> dict[str, Any]:
        return collect_libraries_page_data(self)

    def _collect_dashboard_data(self, stats: dict[str, Any]) -> None:
        collect_dashboard_data(self, stats)
