"""
Workspace paths for clang_github_tracker: state file and raw GitHub activity dir.

Layout:
  workspace/clang_github_activity/
    - state.json
  workspace/raw/github_activity_tracker/<owner>/<repo>/
    - commits/, issues/, prs/
"""

from pathlib import Path

from config.workspace import get_workspace_path

_APP_SLUG = "clang_github_activity"
_RAW_APP_SLUG = "github_activity_tracker"

STATE_FILENAME = "state.json"

# Repo we sync (raw only, no DB)
OWNER = "llvm"
REPO = "llvm-project"


def get_workspace_root() -> Path:
    """Return workspace/clang_github_activity/; creates dir if missing."""
    return get_workspace_path(_APP_SLUG)


def get_state_path() -> Path:
    """Return workspace/clang_github_activity/state.json. Parent dir created on first write."""
    return get_workspace_root() / STATE_FILENAME


def get_raw_root() -> Path:
    """Return workspace/raw/github_activity_tracker/; creates dirs if missing."""
    path = get_workspace_path("raw") / _RAW_APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_repo_dir(owner: str = OWNER, repo: str = REPO) -> Path:
    """Return workspace/raw/github_activity_tracker/<owner>/<repo>/; creates dirs if missing."""
    path = get_raw_root() / owner / repo
    path.mkdir(parents=True, exist_ok=True)
    return path
