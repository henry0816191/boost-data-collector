"""
Workspace paths for cppa_slack_transcript_tracker: data and temp files for huddles.

Layout: workspace/cppa_slack_transcript_tracker/
  - data/<file_id>/  (huddle HTML, result.json, generated markdown)
"""
from pathlib import Path

from config.workspace import get_workspace_path

_APP_SLUG = "cppa_slack_transcript_tracker"


def get_workspace_root() -> Path:
    """Return this app's workspace directory (e.g. workspace/cppa_slack_transcript_tracker/)."""
    return get_workspace_path(_APP_SLUG)


def get_data_dir() -> Path:
    """Return workspace/cppa_slack_transcript_tracker/data/; creates if missing."""
    path = get_workspace_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_working_directory() -> None:
    """Change current working directory to this app's workspace root (for runner)."""
    import os
    root = get_workspace_root()
    os.chdir(root)
