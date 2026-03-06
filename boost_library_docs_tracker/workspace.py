"""
Workspace path helpers for boost_library_docs_tracker.

Layout:
    workspace/
    ├── raw/
    │   └── boost_library_docs_tracker/
    │       └── boost_<version>.zip                  # downloaded source zip
    └── boost_library_docs_tracker/
        ├── extrated/
        │   └── boost_<version>/...                  # extracted HTML/source files
        └── converted/
            └── boost_<version>/...                  # converted page markdown files

Extracted and converted trees share the same relative path structure below
`boost_<version>/`; only their root differs.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from config.workspace import get_workspace_path

APP_SLUG = "boost_library_docs_tracker"


# ---------------------------------------------------------------------------
# Root directories
# ---------------------------------------------------------------------------


def get_app_workspace() -> Path:
    """Return workspace/boost_library_docs_tracker/ (created if missing)."""
    return get_workspace_path(APP_SLUG)


def get_zip_dir() -> Path:
    """Return workspace/raw/boost_library_docs_tracker/ (created if missing)."""
    path = get_app_workspace().parent / "raw" / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_extract_dir() -> Path:
    """Return workspace/boost_library_docs_tracker/extrated/ (created if missing)."""
    path = get_app_workspace() / "extrated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_converted_root() -> Path:
    """Return workspace/boost_library_docs_tracker/converted/ (created if missing)."""
    path = get_app_workspace() / "converted"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------


def get_page_path(version: str, library_name: str, url: str) -> Path:
    """Return converted page file path; preserves extracted relative structure."""
    del version, library_name  # URL is the single source of truth.
    path = resolve_path_from_url(url)
    if path is None:
        raise ValueError(f"Unsupported Boost docs URL: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def save_page(version: str, library_name: str, url: str, text: str) -> Path:
    """Write page markdown to converted workspace and return its path."""
    primary = get_page_path(version, library_name, url)
    primary.write_text(text, encoding="utf-8")
    return primary


def load_page_by_url(url: str) -> str | None:
    """
    Resolve a URL to a workspace file path and return its text, or None if not found.
    The version and library are extracted from the URL path.
    """
    path = resolve_path_from_url(url)
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def resolve_path_from_url(url: str) -> Path | None:
    """
    Derive the workspace file path from a boost.org doc URL.

    URL pattern: https://www.boost.org/doc/libs/<url_version>/libs/<library>/...
    e.g. https://www.boost.org/doc/libs/1_87_0/libs/algorithm/doc/html/index.html

    Returns None if the URL does not match the expected pattern.
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    # Expected: doc / libs / <url_version> / ...
    if len(parts) < 4 or parts[0] != "doc" or parts[1] != "libs":
        return None
    url_version = parts[2]  # e.g. 1_90_0
    relative_parts = parts[3:]  # e.g. libs/utility/doc/html/index.html
    if not relative_parts:
        return None
    return get_converted_root() / f"boost_{url_version}" / Path(*relative_parts).with_suffix(
        ".md"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _url_version(version: str) -> str:
    """Convert version string to URL form: '1.87.0' → '1_87_0'."""
    return version.removeprefix("boost-").replace(".", "_")


def _source_version_dirname(version: str) -> str:
    """Convert version to source-dir form: '1.90.0' -> 'boost_1_90_0'."""
    return f"boost_{_url_version(version)}"
