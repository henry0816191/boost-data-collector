"""
Sync Slack workspace users with the database.

Fetches users via cppa_slack_tracker.fetcher.fetch_user_list and syncs
each via get_or_create_slack_user.
"""

from __future__ import annotations

import logging
from typing import Optional

from cppa_user_tracker.services import get_or_create_slack_user

from cppa_slack_tracker.fetcher import fetch_user_list

logger = logging.getLogger(__name__)


def _process_user_info(
    user_data: dict,
    *,
    include_bots: bool = True,
) -> bool:
    """
    Process one user: skip if bot (unless include_bots), else
    get_or_create_slack_user. Returns True if user was synced, False if skipped.
    Raises on error.
    """
    if not include_bots and user_data.get("is_bot"):
        return False
    get_or_create_slack_user(user_data)
    return True


def sync_users(
    team_slug: str,
    *,
    team_id: Optional[str] = None,
    include_bots: bool = True,
) -> tuple[int, int]:
    """
    Sync workspace users to the database.

    Fetches users via fetch_user_list(team_id) from cppa_slack_tracker.fetcher.
    team_id is required for API token resolution (workspace ID, not slug).
    Processes each user via _process_user_info.

    Returns (success_count, error_count).
    """
    success_count = 0
    error_count = 0

    tid = (team_id or "").strip()
    if not tid:
        logger.error("team_id is required for sync_users (team_slug=%s)", team_slug)
        return success_count, error_count + 1

    try:
        members = fetch_user_list(tid)
    except Exception:
        error_count += 1
        logger.exception(
            "Failed to fetch users for team_slug=%s team_id=%s",
            team_slug,
            team_id,
        )
        return success_count, error_count
    for user_data in members:
        if not isinstance(user_data, dict):
            logger.warning("Skipping malformed user payload: %r", user_data)
            error_count += 1
            continue
        try:
            if _process_user_info(user_data, include_bots=include_bots):
                success_count += 1
        except Exception as e:
            logger.warning(
                "Failed to sync user %s: %s",
                user_data.get("id"),
                e,
            )
            error_count += 1
    return success_count, error_count
