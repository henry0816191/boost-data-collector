"""
Slack message operations: get channel history (messages).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from operations.slack_ops.client import SlackAPIClient
from operations.slack_ops.tokens import get_slack_client

logger = logging.getLogger(__name__)


def get_channel_messages(
    channel_id: str,
    limit: int = 100,
    oldest: Optional[str] = None,
    latest: Optional[str] = None,
    *,
    client: Optional[SlackAPIClient] = None,
) -> list[dict]:
    """
    Get message history for a channel.

    Args:
        channel_id: Slack channel ID (e.g. C01234ABCD).
        limit: Max number of messages (up to 1000 per request).
        oldest: Only messages after this timestamp (optional).
        latest: Only messages before this timestamp (optional).
        client: SlackAPIClient; if None, uses get_slack_client().

    Returns:
        List of message dicts (each has ts, user, text, etc.). Empty list on API error.
    """
    if client is None:
        client = get_slack_client()
    messages = []
    cursor = None
    remaining = limit
    while remaining > 0:
        data = client.conversations_history(
            channel=channel_id,
            limit=min(remaining, 1000),
            oldest=oldest,
            latest=latest,
            cursor=cursor,
        )
        if not data.get("ok"):
            logger.warning(
                "conversations.history failed for %s: %s",
                channel_id,
                data.get("error", "unknown"),
            )
            break
        batch = data.get("messages", [])
        messages.extend(batch)
        if not batch:
            break
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
        remaining -= len(batch)
        if remaining <= 0:
            break
    return messages[:limit] if limit else messages
