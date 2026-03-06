"""
Sync Slack workspace users with the database.

If workspace/cppa_slack_tracker/<team_slug>/users.json exists, process it
(user by user via _process_user_info) then remove the file. Otherwise
fetch users via cppa_slack_tracker.fetcher.fetch_user_list and sync.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from cppa_user_tracker.services import get_or_create_slack_user

from cppa_slack_tracker.fetcher import fetch_user_list
from cppa_slack_tracker.workspace import get_users_json_path

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

    First checks workspace/cppa_slack_tracker/<team_slug>/users.json. If it
    exists, loads it, processes each user via _process_user_info, then
    removes the file. If not, fetches users via fetch_user_list(team_id or
    team_slug) from cppa_slack_tracker.fetcher.

    Returns (success_count, error_count).
    """
    users_path = get_users_json_path(team_slug)
    success_count = 0
    error_count = 0

    members_from_file = None
    if users_path.exists():
        try:
            data = json.loads(users_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                members_from_file = data
            else:
                logger.warning(
                    "Unexpected format in %s (not a list); removing file", users_path
                )
                try:
                    users_path.unlink()
                except OSError as unlink_e:
                    logger.warning("Failed to remove %s: %s", users_path, unlink_e)
        except Exception as e:
            logger.exception("Failed to load %s: %s", users_path, e)
            try:
                users_path.unlink()
            except OSError as unlink_e:
                logger.warning("Failed to remove %s: %s", users_path, unlink_e)

        if members_from_file is not None:
            has_invalid_entry = False
            for user_data in members_from_file:
                if not isinstance(user_data, dict):
                    has_invalid_entry = True
                    error_count += 1
                    logger.warning("Skipping malformed user payload: %r", user_data)
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
            if not has_invalid_entry:
                try:
                    users_path.unlink()
                except OSError as e:
                    logger.warning("Failed to remove %s: %s", users_path, e)
                return success_count, error_count
            # Fall through to API fetch to recover from malformed file content

    # No users.json or load failed: fetch from API
    try:
        members = fetch_user_list(team_id or team_slug)
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
            user_id = user_data.get("id") if isinstance(user_data, dict) else None
            logger.warning(
                "Failed to sync user %s: %s",
                user_id,
                e,
            )
            error_count += 1
    return success_count, error_count
