"""Utility functions for Discord sync."""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string."""
    if not date_str:
        return None

    try:
        # Handle ISO format with Z suffix
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        return datetime.fromisoformat(date_str)
    except (ValueError, AttributeError) as e:
        logger.debug(f"Failed to parse datetime '{date_str}': {e}")
        return None


def parse_discord_user(user_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Parse Discord user data."""
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
        "username": user_data.get("username", "unknown"),
        "display_name": user_data.get("display_name", ""),
        "avatar_url": user_data.get("avatar_url", ""),
        "is_bot": user_data.get("bot", False),
    }


def sanitize_channel_name(channel_name: str) -> str:
    """Sanitize channel name for filenames."""
    # Remove or replace characters that aren't safe for filenames
    safe_name = channel_name.replace("/", "-").replace("\\", "-")
    safe_name = safe_name.replace(":", "-").replace("*", "-")
    safe_name = safe_name.replace("?", "").replace('"', "")
    safe_name = safe_name.replace("<", "").replace(">", "")
    safe_name = safe_name.replace("|", "-")
    return safe_name.strip()


def format_discord_url(server_id: int, channel_id: int, message_id: int) -> str:
    """Format Discord message URL."""
    return f"https://discord.com/channels/{server_id}/{channel_id}/{message_id}"


def truncate_content(content: str, max_length: int = 100) -> str:
    """Truncate content for display."""
    if len(content) <= max_length:
        return content
    return content[:max_length - 3] + "..."
