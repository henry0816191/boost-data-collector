"""Library page data helpers for Boost usage dashboard analyzer."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from github_activity_tracker.models import GitCommitFileChange

from boost_library_tracker.models import BoostDependency
from boost_library_usage_dashboard.utils import _version_tuple


def collect_dependents_data(analyzer: Any) -> dict[int, dict[str, Any]]:
    """Build internal consumer table/chart data from BoostDependency graph."""
    dependencies = BoostDependency.objects.values(  # pylint: disable=no-member
        "client_library_id", "dep_library_id", "version_id"
    )
    version_list = [(v.id, v.version) for v in analyzer.version_info]
    library_id_to_name = {lib["id"]: lib["name"] for lib in analyzer.library_info}

    # Reverse graph for "internal consumers": dep_library -> client_libraries.
    graph: dict[int, dict[int, list[int]]] = {}
    for row in dependencies:
        client = row["client_library_id"]
        dep = row["dep_library_id"]
        version_id = row["version_id"]
        graph.setdefault(dep, {}).setdefault(version_id, []).append(client)

    out: dict[int, dict[str, Any]] = {}
    for library_id in library_id_to_name:
        table_data = []
        chart_data: dict[str, dict[str, int]] = {}
        # Aggregate table rows across versions so panel doesn't end up empty
        # just because the latest version has no consumer edges.
        all_consumers: dict[int, int] = {}
        for version_id, version_name in version_list:
            version_consumers = find_all_transitive_dependencies(
                main_lib_id=library_id,
                version_id=version_id,
                graph=graph,
            )
            first_level = [
                lib_id for lib_id, depth in version_consumers.items() if depth == 1
            ]
            chart_data[version_name] = {
                "first_level": len(first_level),
                # includes primary consumers by definition
                "all_deeper": len(version_consumers),
            }
            for consumer_id, depth in version_consumers.items():
                previous = all_consumers.get(consumer_id)
                if previous is None or depth < previous:
                    all_consumers[consumer_id] = depth
        for client_id, depth in sorted(
            all_consumers.items(),
            key=lambda x: (x[1], library_id_to_name.get(x[0], "")),
        ):
            table_data.append(
                {
                    "name": library_id_to_name.get(client_id, f"Unknown({client_id})"),
                    "depth": depth,
                }
            )
        out[library_id] = {"table_data": table_data, "chart_data": chart_data}
    return out


def find_all_transitive_dependencies(
    main_lib_id: int,
    version_id: int,
    graph: dict[int, dict[int, list[int]]],
) -> dict[int, int]:
    """Return transitive dependencies/consumers with shortest depth."""
    if main_lib_id not in graph or version_id not in graph[main_lib_id]:
        return {}

    all_deps: dict[int, int] = {}
    queue: deque[tuple[int, int]] = deque(
        (dep_id, 1)
        for dep_id in graph[main_lib_id][version_id]
        if dep_id != main_lib_id
    )
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


def collect_commit_info_by_library(analyzer: Any) -> dict[str, Any]:
    """Build per-library contribution map grouped by target version.

    Commit count is by distinct commit: one commit touching N files in the same
    library counts as 1 for that library/version and 1 for that person.
    """
    lib_names = [lib["name"] for lib in analyzer.library_info]
    default = {
        lib_name: {
            version.version: {"count": 0, "persons": {}}
            for version in analyzer.version_info
        }
        for lib_name in lib_names
    }

    rows = (
        GitCommitFileChange.objects.select_related(  # pylint: disable=no-member
            "commit__account__identity",
            "github_file__boost_file__library",
        )
        .filter(github_file__boost_file__isnull=False)
        .exclude(commit__repo__owner_account__username="")
        .iterator()
    )

    # Count by distinct (library, version, commit_id) and (library, version, account_id, commit_id)
    version_commits: dict[tuple[str, str], set[int]] = defaultdict(set)
    person_commits: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {"identity_name": "", "commit_ids": set()})
    )

    for change in rows:
        library = change.github_file.boost_file.library.name
        if library not in default:
            continue

        commit_dt = change.commit.commit_at
        version = get_first_version_released_after(analyzer.version_info, commit_dt)
        if not version:
            continue

        commit_id = change.commit_id
        account_id = change.commit.account_id
        account = change.commit.account
        identity_name = (
            account.identity.display_name
            if account and account.identity_id
            else (
                (account.display_name if account else None)
                or (account.username if account else None)
                or "unknown"
            )
        )

        key = (library, version)
        version_commits[key].add(commit_id)
        person_commits[key][account_id]["identity_name"] = (
            person_commits[key][account_id]["identity_name"] or identity_name
        )
        person_commits[key][account_id]["commit_ids"].add(commit_id)

    for (library, version), commit_ids in version_commits.items():
        default[library][version]["count"] = len(commit_ids)
    for (library, version), by_account in person_commits.items():
        for account_id, data in by_account.items():
            # Key by account_id to keep contributors distinct; no email in output
            default[library][version]["persons"][str(account_id)] = {
                "identity_name": data["identity_name"],
                "commit_count": len(data["commit_ids"]),
            }
    return default


def get_first_version_released_after(
    version_info: list[Any], commit_at: datetime | None
) -> str | None:
    """Return first Boost version whose version_created_at is strictly after commit_at."""
    if commit_at is None:
        return None
    candidates = [
        v
        for v in version_info
        if v.version_created_at is not None and v.version_created_at > commit_at
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda v: v.version_created_at).version


def get_external_consumer_data(
    lib: dict[str, Any], repo_info_dict: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Build external consumer table/chart payload for one library."""
    top_repos_list = lib.get("top_repo_list", {})
    table_data = []
    year_repos: dict[str, int] = {}
    for repo_name, count in top_repos_list.items():
        row = repo_info_dict.get(repo_name, {})
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


def get_contribution_data(lib: dict[str, Any]) -> dict[str, Any]:
    """Build contribution table/chart payload for one library."""
    table_data = []
    chart_data = {}
    for version, data in (lib.get("contribute_data") or {}).items():
        persons = sorted(
            data.get("persons", {}).items(),
            key=lambda x: x[1].get("commit_count", 0),
            reverse=True,
        )
        for _account_key, person_data in persons:
            table_data.append(
                {
                    "version": version,
                    "person": person_data.get("identity_name", ""),
                    "commit_count": person_data.get("commit_count", 0),
                }
            )
        if _version_tuple(version) >= _version_tuple(lib.get("created_version") or ""):
            chart_data[version] = data.get("count", 0)
    table_data.sort(
        key=lambda x: (_version_tuple(x["version"]), x["commit_count"]), reverse=True
    )
    return {"table_data": table_data, "chart_data": chart_data}


def get_last_updated_version(contribute_data: dict[str, Any]) -> str:
    """Return latest version key where contributions exist."""
    versions = [k for k, v in contribute_data.items() if v.get("count", 0) > 0]
    return max(versions, key=_version_tuple) if versions else ""


def build_library_overview_data(
    lib_source: dict[str, Any], lib_data: dict[str, Any]
) -> dict[str, Any]:
    """Compose summary panel data for one library page."""
    contribute_data = lib_source.get("contribute_data", {})
    last_updated_version = get_last_updated_version(contribute_data)
    last_contributors = len(
        contribute_data.get(last_updated_version, {}).get("persons", {})
    )
    overall_contributors = len(
        {
            person
            for data in contribute_data.values()
            for person in data.get("persons", {}).keys()
        }
    )
    internal_consumers = len(
        lib_data.get("internal_dependents_data", {}).get("table_data", [])
    )
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


def collect_libraries_page_data(analyzer: Any) -> dict[str, Any]:
    """Build payload for all per-library dashboard pages."""
    libraries_data: dict[str, Any] = {}
    internal_dependents = collect_dependents_data(analyzer)
    for lib in analyzer.library_info:
        lib_id = lib["id"]
        lib_data = {
            "internal_dependents_data": internal_dependents.get(lib_id, {}),
            "external_consumers": get_external_consumer_data(
                lib, analyzer.repo_info_dict
            ),
            "contribute_data": get_contribution_data(lib),
        }
        lib_data["over_view"] = build_library_overview_data(lib, lib_data)
        libraries_data[lib["name"]] = lib_data
    return libraries_data
