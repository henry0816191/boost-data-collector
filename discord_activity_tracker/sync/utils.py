"""Helpers for Discord sync."""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime."""
    if not date_str:
        return None

    try:
        if date_str.endswith("Z"):
            date_str = date_str[:-1] + "+00:00"
        return datetime.fromisoformat(date_str)
    except (ValueError, AttributeError) as e:
        logger.debug(f"Failed to parse datetime '{date_str}': {e}")
        return None


def parse_discord_user(user_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize user dict from Bot API or DiscordChatExporter."""
    if not user_data:
        return {
            "user_id": 0,
            "username": "unknown",
            "display_name": "",
            "avatar_url": "",
            "is_bot": False,
        }

    return {
        "user_id": user_data.get("id", 0),
        "username": user_data.get("username") or user_data.get("name", "unknown"),
        "display_name": user_data.get("display_name")
        or user_data.get("global_name", ""),
        "avatar_url": user_data.get("avatar_url", ""),
        "is_bot": user_data.get("bot", False),
    }


def sanitize_channel_name(channel_name: str) -> str:
    """Make channel name safe for use in filenames."""
    safe_name = channel_name.replace("/", "-").replace("\\", "-")
    safe_name = safe_name.replace(":", "-").replace("*", "-")
    safe_name = safe_name.replace("?", "").replace('"', "")
    safe_name = safe_name.replace("<", "").replace(">", "")
    safe_name = safe_name.replace("|", "-")
    return safe_name.strip()


def format_discord_url(server_id: int, channel_id: int, message_id: int) -> str:
    """Build Discord message URL."""
    return f"https://discord.com/channels/{server_id}/{channel_id}/{message_id}"


def truncate_content(content: str, max_length: int = 100) -> str:
    """Truncate with ellipsis."""
    if len(content) <= max_length:
        return content
    return content[: max_length - 3] + "..."
