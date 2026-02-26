"""
Workspace paths for boost_mailing_list_tracker: JSON cache for mailing list messages.

Layout:
- Raw: workspace/raw/boost_mailing_list_tracker/<list_name>/<msg_id_safe>.json (kept, not removed)
- Messages: workspace/boost_mailing_list_tracker/<list_name>/messages/<msg_id_safe>.json

Flow (like github_activity_tracker):
1. Process existing JSONs → load, persist to DB, remove file.
2. Fetch from API → save raw to workspace/raw/boost_mailing_list_tracker/<list_name>/, save formatted to messages/, persist to DB, remove formatted file.
"""

import re
from pathlib import Path

from config.workspace import get_workspace_path

_APP_SLUG = "boost_mailing_list_tracker"
_RAW_APP_SLUG = f"raw/{_APP_SLUG}"


def get_workspace_root() -> Path:
    """Return this app's workspace directory (e.g. workspace/boost_mailing_list_tracker/)."""
    return get_workspace_path(_APP_SLUG)


def _safe_msg_id(msg_id: str) -> str:
    """Return a filesystem-safe filename from msg_id (no / \\ : etc.)."""
    stripped = (msg_id or "").strip()
    if not stripped:
        return "unknown"
    safe = re.sub(r'[/\\:*?"<>|]', "_", stripped)
    return safe[:200] if len(safe) > 200 else safe


def get_list_dir(list_name: str) -> Path:
    """Return workspace/boost_mailing_list_tracker/<list_name>/; creates dirs if missing."""
    safe_name = _safe_msg_id(list_name) or "unknown"
    path = get_workspace_root() / safe_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_dir(list_name: str) -> Path:
    """Return workspace/raw/boost_mailing_list_tracker/<list_name>/; creates if missing. Raw scraped data is kept (not removed)."""
    raw_root = get_workspace_path(_RAW_APP_SLUG)
    safe_name = _safe_msg_id(list_name) or "unknown"
    path = raw_root / safe_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_json_path(list_name: str, msg_id: str) -> Path:
    """Path for workspace/raw/boost_mailing_list_tracker/<list_name>/<msg_id_safe>.json. Raw files are not removed after processing."""
    return get_raw_dir(list_name) / f"{_safe_msg_id(msg_id)}.json"


def get_messages_dir(list_name: str) -> Path:
    """Return .../<list_name>/messages/; creates if missing."""
    path = get_list_dir(list_name) / "messages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_message_json_path(list_name: str, msg_id: str) -> Path:
    """Path for messages/<msg_id_safe>.json (parent dir created on first write)."""
    return get_messages_dir(list_name) / f"{_safe_msg_id(msg_id)}.json"


def iter_existing_message_jsons(list_name: str):
    """Yield path for each messages/*.json under workspace/.../<list_name>/messages/."""
    messages_dir = get_workspace_root() / _safe_msg_id(list_name) / "messages"
    if not messages_dir.is_dir():
        return
    for path in messages_dir.glob("*.json"):
        if path.name.startswith("."):
            continue
        yield path


def iter_all_list_dirs():
    """Yield (list_name, messages_dir) for each list subdir that has a messages/ folder."""
    root = get_workspace_root()
    if not root.is_dir():
        return
    for list_dir in root.iterdir():
        if list_dir.is_dir():
            messages_dir = list_dir / "messages"
            if messages_dir.is_dir():
                yield list_dir.name, messages_dir


def iter_all_existing_message_jsons():
    """Yield (list_name, path) for every message JSON in the workspace."""
    for list_name, messages_dir in iter_all_list_dirs():
        for path in messages_dir.glob("*.json"):
            yield list_name, path
