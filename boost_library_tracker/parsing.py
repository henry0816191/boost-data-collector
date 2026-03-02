"""
Parsing helpers for Boost metadata (.gitmodules, meta/libraries.json).
No database access; see services.py for DB operations.
"""

from __future__ import annotations

import json
import re

GITMODULES_PATH_PREFIX = "path = "


def _to_str_list(value: list | str | None) -> list[str]:
    """Return list of non-empty stripped strings; wrap non-list in a list, then clean items."""
    if isinstance(value, list):
        raw_items = value
    elif value:
        raw_items = [value]
    else:
        return []
    cleaned: list[str] = []
    for item in raw_items:
        item_str = str(item).strip() if item is not None else ""
        if item_str:
            cleaned.append(item_str)
    return cleaned


def parse_gitmodules_lib_submodules(gitmodules_content: str) -> list[tuple[str, str]]:
    """
    Parse .gitmodules content and return list of (submodule_name, path)
    for entries whose path starts with "libs/".
    """
    entries: list[tuple[str, str]] = []
    current_name: str | None = None
    current_path: str | None = None
    for line in gitmodules_content.splitlines():
        line = line.strip()
        m = re.match(r'\[submodule\s+"([^"]+)"\]', line)
        if m:
            if current_name is not None and current_path is not None:
                entries.append((current_name, current_path))
            current_name = m.group(1)
            current_path = None
            continue
        if line.startswith(GITMODULES_PATH_PREFIX):
            current_path = line[len(GITMODULES_PATH_PREFIX) :].strip()
    if current_name is not None and current_path is not None:
        entries.append((current_name, current_path))
    return [(n, p) for n, p in entries if p.startswith("libs/")]


def parse_libraries_json_library_names(
    content: str | bytes, submodule_name: str
) -> list[str]:
    """
    Parse meta/libraries.json content and return library display names (first_column).
    Root library: key == submodule_name -> use key. Sub-library: use name.
    """
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            return []
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return []
    if isinstance(raw, list):
        libs = raw
    elif isinstance(raw, dict):
        libs = [raw]
    else:
        return []
    names: list[str] = []
    for obj in libs:
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("key", "")
        key = obj.get("key", "")
        if not name or not key:
            continue
        if key == submodule_name:
            names.append(key)
        else:
            names.append(name)
    return names


def parse_libraries_json_full(content: str | bytes, submodule_name: str) -> list[dict]:
    """
    Parse meta/libraries.json content and return full library data.
    Returns list of dicts with keys: name, key, description, documentation,
    authors, maintainers, category, cxxstd.
    """
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            return []
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return []
    if isinstance(raw, list):
        libs = raw
    elif isinstance(raw, dict):
        libs = [raw]
    else:
        return []

    results: list[dict] = []
    for obj in libs:
        if not isinstance(obj, dict):
            continue

        name = obj.get("name") or obj.get("key", "")
        key = str(obj.get("key") or "")
        if not name or not key:
            continue

        lib_name = key if key == submodule_name else name

        description = str(obj.get("description") or "")
        documentation = str(obj.get("documentation") or "")
        cxxstd = str(obj.get("cxxstd") or "")

        authors = _to_str_list(obj.get("authors", []))
        maintainers = _to_str_list(obj.get("maintainers", []))
        category = _to_str_list(obj.get("category", []))

        results.append(
            {
                "name": lib_name,
                "key": key,
                "description": description,
                "documentation": documentation,
                "authors": authors,
                "maintainers": maintainers,
                "category": category,
                "cxxstd": cxxstd,
            }
        )

    return results
