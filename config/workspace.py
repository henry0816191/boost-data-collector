"""
Workspace paths: one root folder, subfolders per app for raw/processed files.
Use for clone repos, downloaded PDFs, converted output, etc.
"""

from pathlib import Path

from django.conf import settings


def get_workspace_path(app_slug: str) -> Path:
    """
    Return the workspace subfolder for an app. Creates it if missing.

    app_slug: e.g. "github_activity_tracker", "boost_library_tracker", "shared"
    """
    path = Path(settings.WORKSPACE_DIR) / app_slug
    path.mkdir(parents=True, exist_ok=True)
    return path
