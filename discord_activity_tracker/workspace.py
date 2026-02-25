"""Workspace utilities - path helpers for raw export JSON and per-server data."""

from pathlib import Path
from config.workspace import get_workspace_path

_APP_SLUG = "discord_activity_tracker"


def get_workspace_root() -> Path:
    """Return workspace/discord_activity_tracker/."""
    return get_workspace_path(_APP_SLUG)


def get_raw_dir() -> Path:
    """Return workspace/discord_activity_tracker/raw/ for DiscordChatExporter JSON output."""
    path = get_workspace_root() / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_server_dir(server_id: int) -> Path:
    """Return workspace/discord_activity_tracker/<server_id>/ (creates if needed)."""
    path = get_workspace_root() / str(server_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_channel_json_path(server_id: int, channel_id: int) -> Path:
    """Path for <server_id>/channels/<channel_id>.json"""
    path = get_server_dir(server_id) / "channels"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{channel_id}.json"


def get_messages_json_path(server_id: int, channel_id: int, date_str: str) -> Path:
    """Path for <server_id>/messages/<channel_id>/<YYYY-MM-DD>.json"""
    path = get_server_dir(server_id) / "messages" / str(channel_id)
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{date_str}.json"


def iter_existing_message_jsons(server_id: int, channel_id: int):
    """Yield paths for messages/<channel_id>/*.json"""
    messages_dir = get_server_dir(server_id) / "messages" / str(channel_id)
    if not messages_dir.is_dir():
        return
    for path in messages_dir.glob("*.json"):
        yield path
