"""
Sync utilities: parse user/datetime for GitHub data. GitHub client/tokens live in github_ops.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from github_ops import get_github_client, get_github_token

logger = logging.getLogger(__name__)

# Re-export for backward compatibility; prefer "from github_ops import ..."
__all__ = [
    "get_github_client",
    "get_github_token",
    "parse_github_user",
    "parse_datetime",
]


def parse_github_user(user_dict: Optional[dict]) -> dict:
    """Parse GitHub user dict into fields for GitHubAccount. Returns dict with account_id, username, display_name, avatar_url."""
    if user_dict is None:
        return {
            "account_id": None,
            "username": "",
            "display_name": "",
            "avatar_url": "",
        }
    return {
        "account_id": user_dict.get("id"),
        "username": user_dict.get("login", ""),
        "display_name": user_dict.get("name", ""),
        "avatar_url": user_dict.get("avatar_url", ""),
    }


def parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string from GitHub API. Returns datetime or None."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception as e:
        logger.debug(f"Failed to parse datetime '{date_str}': {e}")
        return None
