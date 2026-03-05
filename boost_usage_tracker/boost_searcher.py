"""
Boost include and version detection utilities for boost_usage_tracker.

Uses producer-consumer for file fetching: producer paginates code search and
queues (repo, file_paths); consumer workers fetch file contents in parallel
per repo, with bounded pending futures to limit memory.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from collections import defaultdict
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    as_completed,
    wait,
)  # pylint: disable=no-name-in-module
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from github_ops.client import GitHubAPIClient

logger = logging.getLogger(__name__)

BOOST_INCLUDE_RE = re.compile(r'#include\s*[<"]\s*(boost/[^>"]+)[>"]')
BOOST_VERSION_HPP_PATTERN = re.compile(
    r"#define\s+BOOST_VERSION\s+(\d+)", re.IGNORECASE
)

CMAKE_VERSION_PATTERNS = [
    re.compile(r"find_package\s*\(\s*Boost\s+([0-9.]+)", re.IGNORECASE),
    re.compile(
        r"find_package\s*\(\s*Boost\s+REQUIRED\s+VERSION\s+([0-9.]+)",
        re.IGNORECASE,
    ),
    re.compile(r'set\s*\(\s*BOOST_VERSION\s+["\']([0-9.]+)["\']', re.IGNORECASE),
    re.compile(
        r'set\s*\(\s*MINIMUM_BOOST_VERSION\s+["\']([0-9.]+)["\']',
        re.IGNORECASE,
    ),
    re.compile(r'GIT_TAG\s+["\']boost-([0-9.]+)["\']', re.IGNORECASE),
    re.compile(r"Boost\s+([0-9.]+)\s+REQUIRED", re.IGNORECASE),
    re.compile(r"boost-([0-9.]+)\.tar\.(?:xz|gz|bz2)", re.IGNORECASE),
]

CONAN_VERSION_PATTERNS = [
    re.compile(r"boost/([0-9.]+)", re.IGNORECASE),
    re.compile(r'"boost"\s*:\s*"([0-9.]+)"', re.IGNORECASE),
]

VCPKG_VERSION_PATTERNS = [
    re.compile(
        r'"boost"\s*:\s*\{[^}]*"version"\s*:\s*"([^"]+)"',
        re.IGNORECASE,
    ),
    re.compile(
        r'"name"\s*:\s*"boost"[^}]*"version"\s*:\s*"([^"]+)"',
        re.IGNORECASE,
    ),
]

PER_PAGE = 100
SEARCH_DELAY = 2.0
FILE_FETCH_DELAY = 0.1
PAGE_DELAY = 0.3
GRAPHQL_BATCH_FILE_COUNT = 20

# Producer-consumer: parallel file fetches per repo, bounded pending tasks
MAX_CONCURRENT_FILE_FETCHES = 8
MAX_PENDING_FUTURES = max(
    MAX_CONCURRENT_FILE_FETCHES * 6, MAX_CONCURRENT_FILE_FETCHES + 4
)

MAX_CODE_SEARCH_QUERY_LEN = 255
BOOST_INCLUDE_SEARCH_BATCH_SIZE = 5


@dataclass
class FileSearchResult:
    """A file inside a repository that contains Boost includes."""

    repo_full_name: str
    file_path: str
    content: str = ""
    commit_date: Optional[datetime] = None
    boost_headers: list[str] = field(default_factory=list)


def extract_boost_includes(content: str) -> list[str]:
    """Return Boost header paths found in *content*."""
    return [
        m.group(1).strip()
        for m in BOOST_INCLUDE_RE.finditer(content)
        if m.group(1).strip()
    ]


def _normalize_version(version_str: str) -> Optional[str]:
    version = version_str.replace("-", ".").replace("_", ".")
    if version.startswith("0."):
        return None
    if len(version.split(".")) == 2:
        version = f"{version}.0"
    return version


def extract_boost_version_from_content(
    content: str,
    filename: str,
) -> Optional[str]:
    """Extract a Boost version string from file content."""
    if not content:
        return None

    lower = filename.lower()
    if "version.hpp" in lower:
        match = BOOST_VERSION_HPP_PATTERN.search(content)
        if match:
            ver_int = int(match.group(1))
            major = ver_int // 100_000
            minor = (ver_int // 100) % 1_000
            patch = ver_int % 100
            return f"{major}.{minor}.{patch}"

    if lower in ("cmakelists.txt", "cmakelists.cmake"):
        for pat in CMAKE_VERSION_PATTERNS:
            match = pat.search(content)
            if match:
                return _normalize_version(match.group(1).strip())

    if lower in ("conanfile.txt", "conanfile.py"):
        for pat in CONAN_VERSION_PATTERNS:
            match = pat.search(content)
            if match:
                return _normalize_version(match.group(1).strip())

    if lower == "vcpkg.json":
        for pat in VCPKG_VERSION_PATTERNS:
            match = pat.search(content)
            if match:
                return _normalize_version(match.group(1).strip())

    return None


def get_file_content_with_commit_date(
    client: GitHubAPIClient,
    repo_full_name: str,
    file_path: str,
) -> Optional[dict[str, Any]]:
    """Return {'content': str, 'commit_date': datetime|None} or None."""
    owner, repo_name = repo_full_name.split("/", 1)
    return _get_file_info_graphql(client, owner, repo_name, file_path)


def _get_file_info_graphql(
    client: GitHubAPIClient,
    owner: str,
    repo_name: str,
    file_path: str,
) -> Optional[dict[str, Any]]:
    query = """
        query ($owner: String!, $name: String!, $expression: String!, $filePath: String!) {
            repository(owner: $owner, name: $name) {
                object(expression: $expression) {
                    ... on Blob { text oid }
                }
                defaultBranchRef {
                    target {
                        ... on Commit {
                            history(first: 1, path: $filePath) {
                                edges { node { committedDate oid } }
                            }
                        }
                    }
                }
            }
        }
    """
    try:
        data = client.graphql_request(
            query,
            variables={
                "owner": owner,
                "name": repo_name,
                "expression": f"HEAD:{file_path}",
                "filePath": file_path,
            },
        )
        repo_data = data.get("data", {}).get("repository")
        if not repo_data:
            return None

        blob = repo_data.get("object")
        content = blob.get("text") if blob else None
        if content is None:
            return None

        commit_date = None
        history_edges = (
            repo_data.get("defaultBranchRef", {})
            .get("target", {})
            .get("history", {})
            .get("edges", [])
        )
        if history_edges:
            date_str = history_edges[0]["node"]["committedDate"]
            commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

        return {"content": content, "commit_date": commit_date}
    except Exception as e:
        logger.debug(
            "GraphQL file fetch failed for %s/%s/%s: %s",
            owner,
            repo_name,
            file_path,
            e,
        )
        return None


def _get_file_info_rest(
    client: GitHubAPIClient,
    repo_full_name: str,
    file_path: str,
) -> Optional[dict[str, Any]]:
    try:
        data = client.rest_request(f"/repos/{repo_full_name}/contents/{file_path}")
        if isinstance(data, list):
            return None

        if data.get("encoding") == "base64" and data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
        else:
            content = data.get("content", "")

        commit_date = None
        try:
            commits = client.rest_request(
                f"/repos/{repo_full_name}/commits",
                params={"path": file_path, "per_page": 1},
            )
            if isinstance(commits, list) and commits:
                date_str = commits[0]["commit"]["committer"]["date"]
                commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception as e:
            logger.debug(
                "Failed to fetch commit date for %s/%s: %s",
                repo_full_name,
                file_path,
                e,
            )

        return {"content": content, "commit_date": commit_date}
    except Exception as e:
        logger.debug(
            "REST file fetch failed for %s/%s: %s",
            repo_full_name,
            file_path,
            e,
        )
        return None


def _build_boost_include_query(repo_full_names: list[str]) -> tuple[str, list[str]]:
    """Build a code search query for Boost includes, respecting MAX_CODE_SEARCH_QUERY_LEN.

    Returns (query, remaining_repos). Callers should issue the query, then call again
    with remaining_repos for further batches if non-empty.
    """
    base = '"#include <boost/" language:C++ '
    if not repo_full_names:
        return base, []
    query = base
    remaining: list[str] = []
    for name in repo_full_names:
        part = " " + f"repo:{name}"
        if len(query) + len(part) <= MAX_CODE_SEARCH_QUERY_LEN:
            query += part
        else:
            remaining.append(name)
    return query, remaining


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _get_files_info_graphql_batch(
    client: GitHubAPIClient,
    owner: str,
    repo_name: str,
    file_paths: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetch multiple files from one repo in a single GraphQL request."""
    if not file_paths:
        return {}

    paths = file_paths[:GRAPHQL_BATCH_FILE_COUNT]
    aliases = []
    for idx in range(len(paths)):
        aliases.append(
            f"""
            f{idx}: object(expression: $expr{idx}) {{
              ... on Blob {{ text oid }}
            }}
            h{idx}: defaultBranchRef {{
              target {{
                ... on Commit {{
                  history(first: 1, path: $path{idx}) {{
                    edges {{ node {{ committedDate oid }} }}
                  }}
                }}
              }}
            }}
            """
        )

    query = (
        "query BatchFileQuery($owner: String!, $name: String!"
        + "".join(
            [f", $expr{i}: String!, $path{i}: String!" for i in range(len(paths))]
        )
        + ") { repository(owner: $owner, name: $name) { "
        + " ".join(aliases)
        + " } }"
    )
    variables: dict[str, Any] = {"owner": owner, "name": repo_name}
    for idx, path in enumerate(paths):
        variables[f"expr{idx}"] = f"HEAD:{path}"
        variables[f"path{idx}"] = path

    try:
        data = client.graphql_request(query, variables=variables)
        repo_data = data.get("data", {}).get("repository")
        if not repo_data:
            return {}

        result: dict[str, dict[str, Any]] = {}
        for idx, path in enumerate(paths):
            blob = repo_data.get(f"f{idx}")
            if not blob or blob.get("text") is None:
                continue
            commit_date = None
            history = (
                (repo_data.get(f"h{idx}") or {})
                .get("target", {})
                .get("history", {})
                .get("edges", [])
            )
            if history:
                date_str = history[0]["node"]["committedDate"]
                commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            result[path] = {
                "content": blob.get("text", ""),
                "commit_date": commit_date,
            }
        return result
    except Exception as e:
        logger.debug(
            "GraphQL batch file fetch failed for %s/%s (%d files): %s",
            owner,
            repo_name,
            len(paths),
            e,
        )
        return {}


def _fetch_repo_files_task(
    client: GitHubAPIClient,
    repo_name: str,
    file_paths: list[str],
) -> list[FileSearchResult]:
    """Consumer task: fetch file contents for one repo's paths, return FileSearchResult list."""
    found: list[FileSearchResult] = []
    owner, repo_name_only = repo_name.split("/", 1)
    for path_chunk in _chunked(file_paths, max(1, GRAPHQL_BATCH_FILE_COUNT)):
        batch_data = _get_files_info_graphql_batch(
            client,
            owner,
            repo_name_only,
            path_chunk,
        )
        for path in path_chunk:
            file_info = batch_data.get(path)
            if file_info is None:
                # Fallback only when batch did not return this path.
                file_info = _get_file_info_rest(client, repo_name, path)
            if not file_info:
                continue
            content = file_info.get("content", "")
            # headers = extract_boost_includes(content)
            # if not headers:
            #     continue
            found.append(
                FileSearchResult(
                    repo_full_name=repo_name,
                    file_path=path,
                    content=content,
                    commit_date=file_info.get("commit_date"),
                    boost_headers=[],
                )
            )
        if FILE_FETCH_DELAY > 0:
            time.sleep(FILE_FETCH_DELAY)
    return found


def _search_boost_include_by_query(
    client: GitHubAPIClient,
    query: str,
) -> list[FileSearchResult]:
    """Producer-consumer: paginate code search (producer), fetch file contents in parallel (consumer)."""
    results: list[FileSearchResult] = []
    page = 1
    seen_candidates: set[tuple[str, str]] = set()
    workers = max(1, MAX_CONCURRENT_FILE_FETCHES)
    futures: list[Any] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while True:
            time.sleep(SEARCH_DELAY)
            try:
                data = client.rest_request(
                    "/search/code",
                    params={"q": query, "per_page": PER_PAGE, "page": page},
                )
            except Exception as e:
                logger.warning("Code search failed (page %d): %s", page, e)
                break

            items = data.get("items") or []
            if not items:
                break

            # Producer: enumerate (repo_name, file_path) from this page, group by repo
            repo_to_paths: dict[str, list[str]] = defaultdict(list)
            for item in items:
                path = item.get("path", "")
                if "/boost/" in path.lower() or path.lower().startswith("boost/"):
                    continue
                repo_name = item.get("repository", {}).get("full_name", "")
                if not repo_name or repo_name.lower().startswith("boostorg/"):
                    continue
                key = (repo_name, path)
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                repo_to_paths[repo_name].append(path)

            # Queue consumer tasks (one per repo)
            for repo_name, paths in repo_to_paths.items():
                futures.append(
                    executor.submit(_fetch_repo_files_task, client, repo_name, paths)
                )

            # Backpressure: drain completed futures when too many pending
            if len(futures) >= MAX_PENDING_FUTURES:
                done, not_done = wait(futures, return_when=FIRST_COMPLETED)
                futures = list(not_done)
                for future in done:
                    try:
                        items_found = future.result()
                        if items_found:
                            results.extend(items_found)
                    except Exception as e:
                        logger.debug("File fetch task failed: %s", e)

            if len(items) < PER_PAGE or page >= 10:
                break
            page += 1
            if PAGE_DELAY > 0:
                time.sleep(PAGE_DELAY)

        # Drain remaining futures
        for future in as_completed(futures):
            try:
                items_found = future.result()
                if items_found:
                    results.extend(items_found)
            except Exception as e:
                logger.debug("File fetch task failed: %s", e)

    return results


def search_boost_include_files(
    client: GitHubAPIClient,
    repo_full_name: str,
) -> list[FileSearchResult]:
    query = f'"#include <boost/" language:C++ repo:{repo_full_name}'
    return _search_boost_include_by_query(client, query)


def search_boost_include_files_batch(
    client: GitHubAPIClient,
    repo_full_names: list[str],
) -> list[FileSearchResult]:
    """Find files with '#include <boost/' across a small batch of repos."""
    if not repo_full_names:
        return []
    if len(repo_full_names) == 1:
        return search_boost_include_files(client, repo_full_names[0])

    query, remaining = _build_boost_include_query(repo_full_names)
    repos_in_query = repo_full_names[: len(repo_full_names) - len(remaining)]
    if not repos_in_query:
        return []

    time.sleep(SEARCH_DELAY)
    try:
        probe = client.rest_request(
            "/search/code",
            params={"q": query, "per_page": 1, "page": 1},
        )
    except Exception as e:
        logger.warning("Batch code search probe failed: %s", e)
        return []

    total_count = probe.get("total_count", 0)
    if total_count == 0:
        found = []
    elif total_count > 1000 and len(repos_in_query) > 1:
        mid = len(repos_in_query) // 2
        part1 = search_boost_include_files_batch(client, repos_in_query[:mid])
        part2 = search_boost_include_files_batch(client, repos_in_query[mid:])
        found = part1 + part2
    else:
        found = _search_boost_include_by_query(client, query)

    if remaining:
        found = found + search_boost_include_files_batch(client, remaining)
    return found


def check_repo_has_vendored_boost(
    client: GitHubAPIClient,
    repo_full_name: str,
) -> tuple[bool, Optional[str]]:
    """Check whether *repo_full_name* vendors a Boost copy."""
    time.sleep(SEARCH_DELAY)
    try:
        data = client.rest_request(
            "/search/code",
            params={
                "q": f"filename:version.hpp path:boost repo:{repo_full_name}",
                "per_page": PER_PAGE,
            },
        )
    except Exception:
        return False, None

    if data.get("total_count", 0) == 0:
        return False, None

    for item in data.get("items", []):
        path = item.get("path", "")
        if "boost" not in path.lower() or "version.hpp" not in path.lower():
            continue
        file_info = get_file_content_with_commit_date(client, repo_full_name, path)
        if file_info and file_info.get("content"):
            version = extract_boost_version_from_content(
                file_info["content"], "boost/version.hpp"
            )
            if version:
                return True, version
    return False, None


def detect_boost_version_in_repo(
    client: GitHubAPIClient,
    repo_full_name: str,
) -> tuple[bool, Optional[str]]:
    """Detect the Boost version used by *repo_full_name*."""
    is_vendored, version = check_repo_has_vendored_boost(client, repo_full_name)
    if is_vendored:
        return True, version

    build_files = ["CMakeLists.txt", "conanfile.txt", "conanfile.py", "vcpkg.json"]
    for build_file in build_files:
        file_info = get_file_content_with_commit_date(
            client, repo_full_name, build_file
        )
        if file_info and file_info.get("content"):
            version = extract_boost_version_from_content(
                file_info["content"], build_file
            )
            if version:
                return False, version
    return False, None
