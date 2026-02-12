from __future__ import annotations

import json
import logging
import math
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.db.models import Avg, Count, Max, Min, Q

from boost_library_tracker.models import (
    BoostDependency,
    BoostLibrary,
    BoostLibraryVersion,
    BoostVersion,
)
from cppa_user_tracker.models import Email
from github_activity_tracker.models import GitCommit, GitCommitFileChange

from .models import BoostExternalRepository, BoostUsage
from .utils import format_percent, get_year_repositories_from_md

logger = logging.getLogger(__name__)

STARS_MIN_THRESHOLD = 10


class BoostUsageDashboardAnalyzer:
    def __init__(self, base_dir: Path, output_dir: Path):
        self.base_dir = base_dir
        self.output_dir = output_dir
        self.dashboard_data_file = output_dir / "dashboard_data.json"
        self.report_file = output_dir / "Boost_Usage_Report_total.md"
        self.stars_min_threshold = STARS_MIN_THRESHOLD

        self.version_info = list(BoostVersion.objects.all().order_by("version"))
        self.version_name_list = [v.version for v in self.version_info]
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
            for row in BoostUsage.objects.filter(
                excepted_at__isnull=True,
                repo__githubrepository_ptr__stars__gte=self.stars_min_threshold,
            )
            .values("repo_id")
            .annotate(usage_count=Count("id"))
        }

        repos = (
            BoostExternalRepository.objects.select_related("githubrepository_ptr", "githubrepository_ptr__owner_account")
            .filter(githubrepository_ptr__stars__gte=self.stars_min_threshold)
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
                "created_at": repo.repo_created_at.isoformat() if repo.repo_created_at else "",
                "pushed_at": repo.repo_pushed_at.isoformat() if repo.repo_pushed_at else "",
                "boost_version": ext_repo.boost_version or "",
                "candidate_version": "",
                "usage_count": usage_counts.get(ext_repo.pk, 0),
            }
            if not row["boost_version"] and repo.repo_created_at:
                row["candidate_version"] = self.get_candidate_version_from_created_at(repo.repo_created_at)
            self.repo_info.append(row)
            self.repo_info_dict[full_name] = row

    def _load_library_info(self) -> None:
        by_file_usage = self._calculate_library_metrics_by_file_usage(recent_years=5)
        by_repository = self._calculate_library_metrics_by_repository()
        contribute_data = self._collect_commit_info_by_library()

        libs = BoostLibrary.objects.select_related("repo").all().order_by("name")
        created_versions = {
            row["library_id"]: row["version__version"]
            for row in BoostLibraryVersion.objects.values("library_id")
            .annotate(version__version=Min("version__version"))
        }
        desc_map: dict[int, str] = {}
        for row in (
            BoostLibraryVersion.objects.exclude(description="")
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
            lib_data["contribute_data"] = contribute_data.get(lib.name, {})
            self.library_info.append(lib_data)

    def generate_statistics(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        total_repositories = len(self.repo_info)
        affected_repositories = sum(1 for repo in self.repo_info if repo["affect_from_boost"])
        stats.update(
            {
                "total_repositories": total_repositories,
                "affected_repositories": affected_repositories,
                "total_usage_records": sum(repo["usage_count"] for repo in self.repo_info),
                "total_libraries": len(self.library_info),
            }
        )

        stats["version_related_stats"] = self.get_version_distribution()
        stats["top_libraries"] = self._filter_and_sort_libraries(
            fields=["name", "repo_count", "total_usage", "earliest_commit", "latest_commit"],
            sort_field="repo_count",
            sort_order="DESC",
            limit=20,
        )
        stats["never_used_libraries"] = self._filter_and_sort_libraries(
            fields=["name", "created_version", "last_updated_version"],
            sort_field="created_version",
            sort_order="ASC",
            condition_field="repo_count",
            condition_value=0,
            condition_signal=0,
        )
        stats["top_active_libraries"] = self._filter_and_sort_libraries(
            fields=["name", "total_usage", "recent_usage", "past_usage", "activity_score"],
            sort_field="activity_score",
            sort_order="DESC",
            limit=20,
        )
        stats["bottom_active_libraries"] = self._filter_and_sort_libraries(
            fields=["name", "total_usage", "recent_usage", "past_usage", "activity_score"],
            sort_field="activity_score",
            sort_order="ASC",
            limit=20,
            condition_field="activity_score",
            condition_value=-10,
            condition_signal=1,
        )
        stats["repos_by_year"] = self._get_repository_count_by_year("created_at")
        stats.update(self._load_repository_count_from_md_db(stats["repos_by_year"]))
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
                version_year_counts[version_name][year] = version_year_counts[version_name].get(year, 0) + 1
            if version_name:
                confirmed[version_name] = confirmed.get(version_name, 0) + 1
                continue
            no_version_count += 1
            candidate = repo.get("candidate_version", "")
            guessed[candidate] = guessed.get(candidate, 0) + 1

        distribution = []
        for version in self.version_info:
            created = version.version_created_at.strftime("%Y-%m-%d") if version.version_created_at else ""
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
            "version_coverage_percent": ((total_repositories - no_version_count) / total_repositories * 100) if total_repositories else 0,
            "distribution_by_version": distribution,
            "distribution_by_year_version": version_year_counts,
        }

    def _get_repository_count_by_year(self, time_field: str) -> dict[str, int]:
        repos_by_year: dict[str, int] = {}
        for repo in self.repo_info:
            year = (repo.get(time_field, "") or "")[:4]
            if year:
                repos_by_year[year] = repos_by_year.get(year, 0) + 1
        return repos_by_year

    def _calculate_library_metrics_by_file_usage(self, recent_years: int = 5) -> dict[str, dict[str, Any]]:
        current_year = datetime.now().year - 1
        recent_year_threshold = current_year - recent_years + 1
        rows = (
            BoostUsage.objects.select_related(
                "boost_header__library",
                "boost_header__github_file",
                "repo__githubrepository_ptr",
                "repo__githubrepository_ptr__owner_account",
            )
            .filter(
                excepted_at__isnull=True,
                boost_header__isnull=False,
                repo__githubrepository_ptr__stars__gte=self.stars_min_threshold,
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

            library_headers[library_name][header_name] = library_headers[library_name].get(header_name, 0) + usage_count
            library_top_repo[library_name][repo_name] = library_top_repo[library_name].get(repo_name, 0) + usage_count

        metrics: dict[str, dict[str, Any]] = {}
        for library_name, year_map in library_year_data.items():
            year_data = sorted(year_map.items(), key=lambda x: x[0])
            computed = self.calculate_trend_metrics(year_data, recent_year_threshold)
            sorted_headers = sorted(library_headers.get(library_name, {}).items(), key=lambda x: x[1], reverse=True)
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

    def calculate_trend_metrics(self, year_data: list[tuple[int, dict[str, int]]], recent_year_threshold: int) -> dict[str, float]:
        if not year_data:
            return {"total_usage": 0, "activity_score": -10.0, "recent_usage": 0, "past_usage": 0}
        to_last_year_data = year_data[:-1] if len(year_data) > 1 else year_data
        recent_usage = sum(v["created_count"] for y, v in to_last_year_data if y >= recent_year_threshold)
        past_usage = sum(v["created_count"] for y, v in to_last_year_data if y < recent_year_threshold)
        total_usage = recent_usage + past_usage
        if total_usage == 0:
            return {"total_usage": 0, "activity_score": -10.0, "recent_usage": 0, "past_usage": 0}

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
            sum_xy = sum(x * y for x, y in zip(x_values, ratios))
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
            "activity_score": derivation_score * 0.4 + trend_score * 0.3 + momentum_score * 0.3,
            "recent_usage": recent_usage,
            "past_usage": past_usage,
        }

    def _calculate_library_metrics_by_repository(self) -> dict[str, dict[str, Any]]:
        rows = (
            BoostUsage.objects.filter(
                excepted_at__isnull=True,
                boost_header__isnull=False,
                repo__githubrepository_ptr__stars__gte=self.stars_min_threshold,
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
                "earliest_commit": row["earliest_commit"].strftime("%Y-%m-%d %H:%M:%S") if row["earliest_commit"] else "",
                "latest_commit": row["latest_commit"].strftime("%Y-%m-%d %H:%M:%S") if row["latest_commit"] else "",
                "average_stars": int(row["average_stars"] or 0),
            }
        return metrics

    def _load_repository_count_from_md_db(self, boost_repos_by_year: dict[str, int]) -> dict[str, Any]:
        repo_count_file = self.base_dir / "language_repo_count_report.md"
        if not repo_count_file.exists():
            logger.warning("language_repo_count_report.md not found at %s", repo_count_file)
            return {"repos_by_year_boost_rate": [], "language_comparison_data": {}}
        language_data = get_year_repositories_from_md(repo_count_file)
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
        return {"repos_by_year_boost_rate": repo_data, "language_comparison_data": language_data}

    def _filter_and_sort_libraries(
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
            ret_data.sort(key=lambda x: x.get(sort_field) or 0, reverse=sort_order.lower() == "desc")
        if condition_field:
            if condition_signal > 0:
                ret_data = [lib for lib in ret_data if (lib.get(condition_field) or 0) > condition_value]
            elif condition_signal < 0:
                ret_data = [lib for lib in ret_data if (lib.get(condition_field) or 0) < condition_value]
            else:
                ret_data = [lib for lib in ret_data if (lib.get(condition_field) or 0) == condition_value]
        if limit:
            ret_data = ret_data[:limit]
        return ret_data

    def _collect_top_repositories_for_dashboard(self) -> dict[str, Any]:
        def get_top(feature: str) -> list[dict[str, Any]]:
            return sorted(self.repo_info, key=lambda x: x.get(feature) or "", reverse=True)[:20]

        return {
            "top20_by_stars": get_top("stars"),
            "top20_by_usage": get_top("usage_count"),
            "top20_by_created": get_top("created_at"),
        }

    def _collect_dependents_data(self) -> dict[int, dict[str, Any]]:
        dependencies = BoostDependency.objects.values("client_library_id", "dep_library_id", "version_id")
        version_list = [(v.id, v.version) for v in self.version_info]
        library_id_to_name = {lib["id"]: lib["name"] for lib in self.library_info}

        graph: dict[int, dict[int, list[int]]] = {}
        for row in dependencies:
            client = row["client_library_id"]
            dep = row["dep_library_id"]
            version_id = row["version_id"]
            graph.setdefault(client, {}).setdefault(version_id, []).append(dep)

        out: dict[int, dict[str, Any]] = {}
        for library_id in library_id_to_name:
            table_data = []
            chart_data: dict[str, dict[str, int]] = {}
            all_deps: dict[int, int] = {}
            for version_id, version_name in version_list:
                all_deps = self._find_all_transitive_dependencies(library_id, version_id, graph)
                first_level = [lib_id for lib_id, depth in all_deps.items() if depth == 1]
                chart_data[version_name] = {"first_level": len(first_level), "all_deeper": len(all_deps)}
            for dep_id, depth in sorted(all_deps.items(), key=lambda x: (x[1], library_id_to_name.get(x[0], ""))):
                table_data.append({"name": library_id_to_name.get(dep_id, f"Unknown({dep_id})"), "depth": depth})
            out[library_id] = {"table_data": table_data, "chart_data": chart_data}
        return out

    def _find_all_transitive_dependencies(self, main_lib_id: int, version_id: int, graph: dict[int, dict[int, list[int]]]) -> dict[int, int]:
        if main_lib_id not in graph or version_id not in graph[main_lib_id]:
            return {}
        all_deps: dict[int, int] = {}
        queue: deque[tuple[int, int]] = deque((dep_id, 1) for dep_id in graph[main_lib_id][version_id] if dep_id != main_lib_id)
        visited = {main_lib_id}
        while queue:
            lib_id, depth = queue.popleft()
            if lib_id in visited:
                continue
            visited.add(lib_id)
            all_deps[lib_id] = depth
            for nxt in graph.get(lib_id, {}).get(version_id, []):
                if nxt not in visited and nxt != main_lib_id:
                    queue.append((nxt, depth + 1))
        return all_deps

    def _collect_commit_info_by_library(self) -> dict[str, Any]:
        lib_names = [lib["name"] for lib in self.library_info]
        default = {
            lib_name: {version.version: {"count": 0, "persons": {}} for version in self.version_info}
            for lib_name in lib_names
        }
        rows = (
            GitCommitFileChange.objects.select_related(
                "commit__account__identity",
                "github_file__boost_file__library",
            )
            .filter(github_file__boost_file__isnull=False)
            .exclude(commit__repo__owner_account__username="")
            .iterator()
        )
        email_map = {
            row["base_profile_id"]: row["email"]
            for row in Email.objects.filter(is_primary=True).values("base_profile_id", "email")
        }
        for change in rows:
            library = change.github_file.boost_file.library.name
            if library not in default:
                continue
            commit_dt = change.commit.commit_at
            version = self._normalize_and_moving_version(self.get_candidate_version_from_created_at(commit_dt), forward_step=1)
            if not version:
                continue
            email = email_map.get(change.commit.account_id, "")
            identity_name = (
                change.commit.account.identity.display_name
                if change.commit.account.identity_id
                else (change.commit.account.display_name or change.commit.account.username or email or "unknown")
            )
            if not email:
                email = f"{change.commit.account.username or 'unknown'}@unknown"
            default[library][version]["count"] += 1
            person = default[library][version]["persons"].setdefault(email, {"identity_name": identity_name, "commit_count": 0})
            person["commit_count"] += 1
        return default

    def _normalize_and_moving_version(self, version: str, forward_step: int = 0) -> str | None:
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
        top_repos_list = lib.get("top_repo_list", {})
        table_data = []
        year_repos: dict[str, int] = {}
        for repo_name, count in top_repos_list.items():
            row = self.repo_info_dict.get(repo_name, {})
            created_at = (row.get("created_at") or "")[:10]
            updated_at = (row.get("pushed_at") or "")[:10]
            table_data.append(
                {
                    "name": repo_name,
                    "stars": row.get("stars", 0),
                    "usage_count": count,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
            year = created_at[:4] if created_at else ""
            if year:
                year_repos[year] = year_repos.get(year, 0) + 1
        year_data = {}
        for year, count in lib.get("year_data", {}).items():
            year_data[year] = {
                "by_created": count.get("created_count", 0),
                "by_last_commit": count.get("last_commit_count", 0),
                "repos": year_repos.get(year, 0),
            }
        return {"table_data": table_data, "chart_data": year_data}

    def _get_contribution_data(self, lib: dict[str, Any]) -> dict[str, Any]:
        table_data = []
        chart_data = {}
        for version, data in (lib.get("contribute_data") or {}).items():
            persons = sorted(data.get("persons", {}).items(), key=lambda x: x[1].get("commit_count", 0), reverse=True)
            for email, person_data in persons:
                table_data.append(
                    {
                        "version": version,
                        "person": person_data.get("identity_name", ""),
                        "email_address": email,
                        "commit_count": person_data.get("commit_count", 0),
                    }
                )
            if version >= (lib.get("created_version") or ""):
                chart_data[version] = data.get("count", 0)
        table_data.sort(key=lambda x: (x["version"], x["commit_count"]), reverse=True)
        return {"table_data": table_data, "chart_data": chart_data}

    def _get_last_updated_version(self, contribute_data: dict[str, Any]) -> str:
        versions = [k for k, v in contribute_data.items() if v.get("count", 0) > 0]
        return max(versions) if versions else ""

    def _build_library_overview_data(self, lib_source: dict[str, Any], lib_data: dict[str, Any]) -> dict[str, Any]:
        contribute_data = lib_source.get("contribute_data", {})
        last_updated_version = self._get_last_updated_version(contribute_data)
        last_contributors = len(contribute_data.get(last_updated_version, {}).get("persons", {}))
        overall_contributors = len(
            {
                person
                for data in contribute_data.values()
                for person in data.get("persons", {}).keys()
            }
        )
        internal_consumers = len(lib_data.get("internal_dependents_data", {}).get("table_data", []))
        year_count = lib_data.get("external_consumers", {}).get("chart_data", {})
        total_count = 0
        max_repo_count = 0
        max_year = ""
        last_year = datetime.now().year - 1
        last_year_repo_count = year_count.get(str(last_year), {}).get("repos", 0)
        for year, data in year_count.items():
            repo_count = data.get("repos", 0)
            total_count += repo_count
            if repo_count > max_repo_count:
                max_repo_count = repo_count
                max_year = year
        average_used_repo_count = int(total_count / len(year_count)) if year_count else 0
        return {
            "created_version": lib_source.get("created_version", ""),
            "last_updated_version": last_updated_version,
            "last_contributors": last_contributors,
            "overall_contributors": overall_contributors,
            "internal_consumers": internal_consumers,
            "used_repo_count": lib_source.get("repo_count", 0),
            "average_used_repo_count": average_used_repo_count,
            "active_score": lib_source.get("activity_score", 0),
            "average_star": lib_source.get("average_stars", 0),
            "description": lib_source.get("description", ""),
            "most_used_year": {"year": max_year, "count": max_repo_count},
            "last_year_used_repo_count": {"year": last_year, "count": last_year_repo_count},
            "used_headers": lib_source.get("used_headers", {}),
        }

    def _collect_libraries_page_data(self) -> dict[str, Any]:
        libraries_data: dict[str, Any] = {}
        internal_dependents = self._collect_dependents_data()
        for lib in self.library_info:
            lib_id = lib["id"]
            lib_data = {
                "internal_dependents_data": internal_dependents.get(lib_id, {}),
                "external_consumers": self._get_external_consumer_data(lib),
                "contribute_data": self._get_contribution_data(lib),
            }
            lib_data["over_view"] = self._build_library_overview_data(lib, lib_data)
            libraries_data[lib["name"]] = lib_data
        return libraries_data

    def _collect_dashboard_data(self, stats: dict[str, Any]) -> None:
        dashboard_data: dict[str, Any] = {}
        dashboard_data["repos_by_year"] = stats["repos_by_year"]
        version_counts = stats["version_related_stats"]["distribution_by_version"]
        dashboard_data["repos_by_version"] = sorted(
            [(version, confirmed + guessed) for version, _, confirmed, guessed in version_counts],
            key=lambda x: x[0],
        )
        dashboard_data["repos_by_year_boost_rate"] = stats["repos_by_year_boost_rate"]
        dashboard_data["language_comparison_data"] = stats["language_comparison_data"]
        dashboard_data["metrics_by_library"] = self._filter_and_sort_libraries(
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
        dashboard_data["top_repositories"] = self._collect_top_repositories_for_dashboard()
        dashboard_data["libraries_page_data"] = self._collect_libraries_page_data()
        dashboard_data["all_versions_for_chart"] = self.version_name_list

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.dashboard_data_file.write_text(json.dumps(dashboard_data, indent=2, ensure_ascii=False), encoding="utf-8")

