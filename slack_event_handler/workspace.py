"""
Workspace paths for slack_event_handler.

Layout: workspace/slack_event_handler/
  - data/  (state.json, raw event files)
"""

import os
from pathlib import Path

from config.workspace import get_workspace_path

_APP_SLUG = "slack_event_handler"


def get_workspace_root() -> Path:
    """Return this app's workspace directory (e.g. workspace/slack_event_handler/)."""
    return get_workspace_path(_APP_SLUG)


def get_data_dir() -> Path:
    """Return workspace/slack_event_handler/data/; creates if missing."""
    path = get_workspace_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_working_directory() -> None:
    """Change current working directory to this app's workspace root (for runner)."""
    root = get_workspace_root()
    os.chdir(root)
