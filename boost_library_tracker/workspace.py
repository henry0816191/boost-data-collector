"""
Workspace paths for boost_library_tracker: raw clones, output files, etc.

Layout: workspace/raw/<app>/  (e.g. clone of boostorg/boost for running get_deps.sh)
"""

from pathlib import Path

from django.conf import settings

from config.workspace import get_workspace_path

_APP_SLUG = "boost_library_tracker"


def get_workspace_root() -> Path:
    """Return this app's workspace directory (e.g. workspace/boost_library_tracker/)."""
    return get_workspace_path(_APP_SLUG)


def get_raw_dir() -> Path:
    """Return workspace/raw/boost_library_tracker/; creates dir if missing."""
    path = Path(settings.WORKSPACE_DIR) / "raw" / _APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_boost_clone_dir() -> Path:
    """Return workspace/raw/boost_library_tracker/boost/; use this as clone dir for boostorg/boost."""
    path = get_raw_dir() / "boost"
    path.mkdir(parents=True, exist_ok=True)
    return path
