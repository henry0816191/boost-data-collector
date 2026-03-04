"""
Workspace paths for cppa_slack_tracker: JSON cache for messages, etc.

Layout (refer workspace/cppa_slack_tracker/Cpplang):
  - workspace/cppa_slack_tracker/<team_slug>/<channel_slug>/YYYY-MM-DD.json
  - RAW_DIR/cppa_slack_tracker/<team_slug>/<channel_slug>/YYYY-MM-DD.json
  (RAW_DIR defaults to workspace/raw when unset; see settings.RAW_DIR.)
"""

from datetime import datetime
from pathlib import Path

from django.conf import settings

from config.workspace import get_workspace_path
from operations.file_ops import sanitize_filename

_APP_SLUG = "cppa_slack_tracker"


def _validate_date_str(date_str: str) -> str:
    """Ensure date_str is YYYY-MM-DD only; reject path separators and '..' to prevent path traversal."""
    if "/" in date_str or ".." in date_str:
        raise ValueError(
            "date_str must be in YYYY-MM-DD format and must not contain path separators or '..'"
        )
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as err:
        raise ValueError("date_str must be in YYYY-MM-DD format") from err
    return date_str


def _is_daily_message_json(path: Path) -> bool:
    """True if path is a .json file whose stem is YYYY-MM-DD."""
    if path.suffix != ".json":
        return False
    try:
        datetime.strptime(path.stem, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def get_workspace_root() -> Path:
    """Return this app's workspace directory (e.g. workspace/cppa_slack_tracker/)."""
    return get_workspace_path(_APP_SLUG)


def get_raw_root() -> Path:
    """Return raw root for this app (e.g. RAW_DIR/cppa_slack_tracker/ or workspace/raw/cppa_slack_tracker/)."""
    raw_base = getattr(settings, "RAW_DIR", None)
    if not raw_base:
        raw_base = Path(settings.WORKSPACE_DIR) / "raw"
    path = Path(raw_base) / _APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(name: str) -> str:
    """Sanitize name for use as path segment (team_slug, channel_slug)."""
    if not name or not str(name).strip():
        return "unknown"
    return sanitize_filename(str(name).strip()).strip("_") or "unknown"


def get_users_json_path(team_slug: str) -> Path:
    """Return workspace path: workspace/cppa_slack_tracker/<team_slug>/users.json."""
    return get_workspace_path(_APP_SLUG) / _slug(team_slug) / "users.json"


def get_channels_json_path(team_slug: str) -> Path:
    """Return workspace path: workspace/cppa_slack_tracker/<team_slug>/channels.json."""
    return get_workspace_root() / _slug(team_slug) / "channels.json"


def get_members_json_path(team_slug: str, channel_slug: str) -> Path:
    """Return workspace path: workspace/cppa_slack_tracker/<team_slug>/<channel_slug>/members.json."""
    return (
        get_workspace_root() / _slug(team_slug) / _slug(channel_slug) / "members.json"
    )


def get_team_channel_dir(team_slug: str, channel_slug: str) -> Path:
    """Return workspace/cppa_slack_tracker/<team_slug>/<channel_slug>/; creates dirs if missing."""
    path = get_workspace_root() / _slug(team_slug) / _slug(channel_slug)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_message_json_path(team_slug: str, channel_slug: str, date_str: str) -> Path:
    """Return workspace path for messages on a given day: .../<team_slug>/<channel_slug>/YYYY-MM-DD.json."""
    safe_date = _validate_date_str(date_str)
    return get_team_channel_dir(team_slug, channel_slug) / f"{safe_date}.json"


def get_raw_team_channel_dir(team_slug: str, channel_slug: str) -> Path:
    """Return raw dir for this app: RAW_DIR/cppa_slack_tracker/<team_slug>/<channel_slug>/; creates dirs if missing."""
    path = get_raw_root() / _slug(team_slug) / _slug(channel_slug)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_message_json_path(team_slug: str, channel_slug: str, date_str: str) -> Path:
    """Return raw path for messages on a given day: RAW_DIR/.../<team_slug>/<channel_slug>/YYYY-MM-DD.json."""
    safe_date = _validate_date_str(date_str)
    return get_raw_team_channel_dir(team_slug, channel_slug) / f"{safe_date}.json"


def get_messages_dir() -> Path:
    """Return workspace/cppa_slack_tracker/messages/; creates dir if missing (legacy)."""
    path = get_workspace_root() / "messages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def iter_existing_message_jsons(
    team_slug: str | None = None, channel_slug: str | None = None
):
    """
    Yield Path for each YYYY-MM-DD.json under workspace.

    If team_slug is set, only under workspace/<team_slug>/.
    If channel_slug is also set, only under workspace/<team_slug>/<channel_slug>/.
    """
    root = get_workspace_root()
    if not root.exists():
        return
    if team_slug and channel_slug:
        base = root / _slug(team_slug) / _slug(channel_slug)
        if not base.is_dir():
            return
        for path in sorted(base.glob("*.json")):
            if _is_daily_message_json(path):
                yield path
        return
    if team_slug:
        base = root / _slug(team_slug)
        if not base.is_dir():
            return
        for channel_dir in sorted(base.iterdir()):
            if channel_dir.is_dir():
                for path in sorted(channel_dir.glob("*.json")):
                    if _is_daily_message_json(path):
                        yield path
        return
    for team_dir in sorted(root.iterdir()):
        if not team_dir.is_dir() or team_dir.name == "messages":
            continue
        for channel_dir in sorted(team_dir.iterdir()):
            if channel_dir.is_dir():
                for path in sorted(channel_dir.glob("*.json")):
                    if _is_daily_message_json(path):
                        yield path
