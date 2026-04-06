"""
Pinecone preprocess function for cppa_slack_tracker.

Guideline source:
- docs/Pinecone_preprocess_guideline.md

This module returns whole-document payloads (is_chunked=False) so the sync
pipeline can apply its configured chunking strategy.

Adapted from workspace/slack_preprocessor.py to use Django ORM instead of
direct PostgreSQL queries.
"""

from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Any, Optional, Dict, List

from django.conf import settings
from django.db.models import Q

from cppa_slack_tracker.models import SlackMessage
from cppa_slack_tracker.utils import (
    clean_text,
    filter_sentence,
    validate_content_length,
)

logger = logging.getLogger(__name__)

# Maximum seconds between messages to consider them "consecutive" (same user merge)
CONSECUTIVE_MESSAGE_WINDOW_SECONDS = 3600  # 1 hour


def _normalize_failed_ids(failed_ids: list[str]) -> list[str]:
    """Return stripped, non-empty, de-duplicated failed IDs preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in failed_ids:
        value = (raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _get_user_name(message: SlackMessage) -> str:
    """Extract user name from message."""
    if message.user:
        return message.user.display_name or message.user.username or "unknown"
    return "unknown"


def _clean_slack_text(text: str) -> str:
    """Clean Slack-specific formatting from text."""
    # Remove user mentions <@U123456>
    text = re.sub(r"<@[A-Z0-9]+>", "", text)

    # Convert channel mentions <#C123456|channel-name> to #channel-name
    text = re.sub(r"<#([A-Z0-9]+)\|([^>]+)>", r"#\2", text)

    # Convert URLs <https://example.com|link text> to link text
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<([^>]+)>", r"\1", text)

    # Remove emoji codes :emoji_name:
    text = re.sub(r":[\w+-]+:", "", text)

    # Clean up extra whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _filter_unessential_words(text: str) -> str:
    """Remove greeting words, unessential words, and emoji patterns from text."""
    if not text:
        return ""

    text = _clean_slack_text(text)
    text = re.sub(r":[\w+-]+:", "", text)  # Remove emoji patterns
    text = clean_text(text, remove_extra_spaces=True)

    sentences = re.split(r"[.!?]\s+", text)
    filtered = []
    for s in sentences:
        if not s.strip():
            continue
        f = filter_sentence(s, min_words_after=settings.PINECONE_MIN_WORDS)
        if f:
            filtered.append(f)
    return ". ".join(filtered).strip()


def _group_by_thread(
    messages: List[SlackMessage],
) -> Dict[Optional[str], List[SlackMessage]]:
    """Group messages by thread_ts."""
    groups: Dict[Optional[str], List[SlackMessage]] = {}
    for msg in messages:
        thread_ts = msg.thread_ts
        if thread_ts not in groups:
            groups[thread_ts] = []
        groups[thread_ts].append(msg)
    return groups


def _extract_valid_messages(
    messages: List[SlackMessage],
) -> tuple[List[str], List[str]]:
    """Extract and filter valid messages, returning text parts and message IDs."""
    merged_parts = []
    message_ids = []
    for msg in messages:
        text = (msg.message or "").strip()
        if not text:
            continue
        filtered = _filter_unessential_words(text)
        if filtered and validate_content_length(
            filtered, min_length=settings.PINECONE_MIN_TEXT_LENGTH
        ):
            merged_parts.append(filtered)
            if msg.ts:
                message_ids.append(msg.ts)
    return merged_parts, message_ids


def _merge_thread_messages(
    thread_messages: List[SlackMessage], thread_ts: str
) -> Optional[Dict[str, Any]]:
    """Merge all messages in a thread into one text after filtering unessential words."""
    if not thread_messages:
        return None

    merged_parts, message_ids = _extract_valid_messages(thread_messages)
    if not merged_parts:
        return None

    first_msg = thread_messages[0]
    return {
        "id": first_msg.ts or "",
        "message_ids": message_ids,
        "text": " ".join(merged_parts),
        "user_name": _get_user_name(first_msg),
        "channel_id": (first_msg.channel.channel_id if first_msg.channel else ""),
        "ts": first_msg.ts,
        "thread_ts": thread_ts,
        "is_grouped": True,
        "team_id": first_msg.channel.team.team_id if first_msg.channel else "",
    }


def _is_consecutive_message(
    current_group: Dict[str, Any], next_msg: SlackMessage
) -> bool:
    """Check if next message is consecutive (within 60 minutes) to current group."""
    try:
        start_ts = float(current_group.get("start_ts", 0))
        next_ts = float(next_msg.ts or 0)

        # Consider consecutive if within CONSECUTIVE_MESSAGE_WINDOW_SECONDS
        time_diff = next_ts - start_ts
        return 0 < time_diff <= CONSECUTIVE_MESSAGE_WINDOW_SECONDS
    except (ValueError, TypeError):
        return False


def _create_message_group(
    msg: SlackMessage, user_name: str, text: str
) -> Dict[str, Any]:
    """Create a new message group dictionary."""
    return {
        "id": msg.ts,
        "message_ids": [msg.ts] if msg.ts else [],
        "text": text,
        "user_name": user_name,
        "channel_id": msg.channel.channel_id if msg.channel else "",
        "ts": msg.ts,
        "thread_ts": msg.thread_ts,
        "is_grouped": True,
        "start_ts": msg.ts,
        "team_id": msg.channel.team.team_id if msg.channel else "",
    }


def _merge_by_user_name(messages: List[SlackMessage]) -> List[Dict[str, Any]]:
    """Merge messages from the same user."""
    merged_groups = []
    current_group: Optional[Dict[str, Any]] = None

    for msg in messages:
        text = _filter_unessential_words((msg.message or "").strip())
        if not text:
            continue

        user_name = _get_user_name(msg)
        if (
            current_group is not None
            and current_group.get("user_name") == user_name
            and _is_consecutive_message(current_group, msg)
        ):
            assert current_group is not None  # Type narrowing
            current_group["text"] += " " + text
            if msg.ts:
                current_group["message_ids"].append(msg.ts)
            current_group["ts"] = msg.ts
        else:
            if current_group is not None:
                merged_groups.append(current_group)
            current_group = _create_message_group(msg, user_name, text)

    if current_group is not None:
        merged_groups.append(current_group)
    return merged_groups


def _merge_consecutive_messages(
    groups: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge consecutive message groups that are close in time."""
    if not groups:
        return []
    merged_groups = []
    current_group = groups[0].copy()
    for group in groups[1:]:
        # Check if consecutive based on timestamps
        try:
            current_ts = float(current_group.get("ts", 0))
            group_ts = float(group.get("ts", 0))
            time_diff = group_ts - current_ts
            if 0 < time_diff <= CONSECUTIVE_MESSAGE_WINDOW_SECONDS:
                current_group["text"] += " " + group["text"]
                current_group["message_ids"].extend(group["message_ids"])
                current_group["ts"] = group["ts"]
            else:
                merged_groups.append(current_group)
                current_group = group.copy()
        except (ValueError, TypeError):
            merged_groups.append(current_group)
            current_group = group.copy()
    merged_groups.append(current_group)
    return merged_groups


def _merge_none_thread_messages(
    messages: List[SlackMessage],
) -> List[Dict[str, Any]]:
    """Merge consecutive messages from the same user."""
    if not messages:
        return []
    first_group = _merge_by_user_name(messages)
    final_group = _merge_consecutive_messages(first_group)
    return final_group


def filter_and_group_messages(
    messages: List[SlackMessage],
) -> List[Dict[str, Any]]:
    """Filter and group messages by thread, merging consecutive messages from same user."""
    if not messages:
        return []

    thread_groups = _group_by_thread(messages)
    grouped_messages = []
    for thread_ts, thread_messages in thread_groups.items():
        # Sort by timestamp
        thread_messages.sort(key=lambda m: float(m.ts or 0))
        if thread_ts is not None:
            if group := _merge_thread_messages(thread_messages, thread_ts):
                grouped_messages.append(group)
        else:
            grouped_messages.extend(_merge_none_thread_messages(thread_messages))
    return grouped_messages


def _build_document_content(group: Dict[str, Any]) -> str:
    """Build plain-text content for embedding."""
    text = group.get("text", "").strip()
    if not validate_content_length(text, min_length=settings.PINECONE_MIN_TEXT_LENGTH):
        return ""
    return text


def preprocess_slack_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Build Pinecone sync documents for Slack messages.

    Args:
        failed_ids: Previous-run failed source IDs (we store/retry ts values).
        final_sync_at: Last sync timestamp for incremental sync; None means first sync.

    Returns:
        (documents, is_chunked)
        - documents: list[{"content": str, "metadata": dict}]
        - is_chunked: False (whole docs; ingestion pipeline may chunk later)
    """
    normalized_failed = _normalize_failed_ids(failed_ids or [])

    # Query SlackMessage with efficient joins
    queryset = SlackMessage.objects.select_related("channel__team", "user").order_by(
        "ts"
    )

    messages_new = []
    messages_failed = []

    if final_sync_at is None and not normalized_failed:
        # First sync - get all messages
        candidates_new = queryset
        messages_new = list(candidates_new)
        logger.info(
            f"Loaded {len(messages_new)} Slack messages for preprocessing (first sync)"
        )
    else:
        if final_sync_at is not None:
            # Incremental sync: get messages created/updated after last sync
            # Use slack_message_created_at since SlackMessage doesn't have created_at
            criteria_new = Q(slack_message_updated_at__gt=final_sync_at)
            candidates_new = queryset.filter(criteria_new)
            messages_new = list(candidates_new)
            logger.info(
                f"Loaded {len(messages_new)} new Slack messages for preprocessing"
            )
        if normalized_failed:
            # Retry failed messages
            criteria_failed = Q(ts__in=normalized_failed)
            candidates_failed = queryset.filter(criteria_failed)
            messages_failed = list(candidates_failed)
            logger.info(
                f"Loaded {len(messages_failed)} failed Slack messages for preprocessing"
            )

    # Group and filter messages
    grouped_messages = []
    if messages_new:
        grouped_messages.extend(filter_and_group_messages(messages_new))
    if messages_failed:
        grouped_messages.extend(filter_and_group_messages(messages_failed))

    logger.info(f"Grouped into {len(grouped_messages)} document groups after filtering")

    # Build document dicts
    docs: list[dict[str, Any]] = []
    seen_ts: set[str] = set()

    for group in grouped_messages:
        ts = group.get("ts", "").strip()
        if not ts or ts in seen_ts:
            continue
        seen_ts.add(ts)

        content = _build_document_content(group)
        if not content:
            continue

        message_ids = group.get("message_ids", [ts] if ts else [])
        channel_id = group.get("channel_id", "")
        user_name = group.get("user_name", "unknown")
        thread_ts = group.get("thread_ts", "")
        is_grouped = group.get("is_grouped", False)
        team_id = group.get("team_id", "")

        # Convert timestamp string to int for metadata
        try:
            safe_timestamp = int(float(ts))
        except (ValueError, TypeError):
            safe_timestamp = 0

        metadata: dict[str, Any] = {
            "doc_id": ts,
            "type": "slack",
            "channel_id": channel_id,
            "user_name": user_name,
            "timestamp": safe_timestamp,
            "is_grouped": is_grouped,
            "thread_ts": thread_ts if thread_ts else "",
            "group_size": len(message_ids),
            "team_id": team_id,
            "source_ids": ",".join(message_ids),
        }

        docs.append({"content": content, "metadata": metadata})

    logger.info(f"Built {len(docs)} documents for Pinecone sync")

    return docs, False
