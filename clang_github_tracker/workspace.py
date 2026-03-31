"""
Workspace paths for clang_github_tracker: md export, backfill CSV dir, raw GitHub JSON.

Layout:
  workspace/clang_github_activity/
    - md_export/  (generated Markdown for private repo push)
  workspace/clang_github_tracker/
    - clang_github_tracker_backfill.csv (default CSV backfill path)
  workspace/raw/github_activity_tracker/<owner>/<repo>/
    - commits/, issues/, prs/
"""

import re
from pathlib import Path

from django.conf import settings

from config.workspace import get_workspace_path

_APP_SLUG = "clang_github_activity"
_TRACKER_DATA_SLUG = "clang_github_tracker"
_RAW_APP_SLUG = "github_activity_tracker"

DEFAULT_BACKFILL_CSV_NAME = "clang_github_tracker_backfill.csv"

# Repo we sync (raw only, no DB); from settings (env: CLANG_GITHUB_OWNER, CLANG_GITHUB_REPO)
OWNER = settings.CLANG_GITHUB_OWNER
REPO = settings.CLANG_GITHUB_REPO

# Safe path segment: alphanumeric, underscore, hyphen, dot (GitHub owner/repo style)
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _sanitize_segment(value: str, label: str) -> str:
    """Validate owner/repo for use as a path segment; reject traversal, separators, empty."""
    value = (value or "").strip()
    if not value or not _SEGMENT_RE.fullmatch(value):
        raise ValueError(f"Invalid GitHub {label}: {value!r}")
    return value


def get_workspace_root() -> Path:
    """Return workspace/clang_github_activity/; creates dir if missing."""
    return get_workspace_path(_APP_SLUG)


def get_clang_github_tracker_data_dir() -> Path:
    """Return workspace/clang_github_tracker/; creates dir if missing."""
    path = get_workspace_path(_TRACKER_DATA_SLUG)
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_backfill_csv_path() -> Path:
    """Default path for CSV backfill: workspace/clang_github_tracker/<DEFAULT_BACKFILL_CSV_NAME>."""
    return get_clang_github_tracker_data_dir() / DEFAULT_BACKFILL_CSV_NAME


def get_raw_root() -> Path:
    """Return workspace/raw/github_activity_tracker/; creates dirs if missing."""
    path = get_workspace_path("raw") / _RAW_APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_repo_dir(
    owner: str = OWNER, repo: str = REPO, *, create: bool = True
) -> Path:
    """Return workspace/raw/github_activity_tracker/<owner>/<repo>/; creates dirs if missing when create=True."""
    safe_owner = _sanitize_segment(owner, "owner")
    safe_repo = _sanitize_segment(repo, "repo")
    path = get_raw_root() / safe_owner / safe_repo
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
