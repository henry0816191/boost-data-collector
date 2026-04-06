"""
Pinecone preprocess function for boost_mailing_list_tracker.

Guideline source:
- docs/Pinecone_preprocess_guideline.md

This module returns whole-document payloads (is_chunked=False) so the sync
pipeline can apply its configured chunking strategy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Q

from boost_mailing_list_tracker.models import MailingListMessage


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


def _get_sender_display_name(sender: Any) -> str:
    """Return trimmed display name from sender (display_name or identity.display_name)."""
    return (getattr(sender, "display_name", "") or "").strip() or (
        getattr(getattr(sender, "identity", None), "display_name", "") or ""
    ).strip()


def _build_document_content(message: MailingListMessage) -> str:
    """
    Build plain-text content for embedding.

    Keep this stable and readable so future chunking preserves useful context.
    """
    parts: list[str] = []
    if message.subject:
        parts.append(f"Subject: {message.subject.strip()}")

    sender_name = _get_sender_display_name(message.sender)
    if sender_name:
        parts.append(f"Sender: {sender_name}")

    if message.list_name:
        parts.append(f"List: {message.list_name}")
    if message.sent_at:
        parts.append(f"Sent At: {message.sent_at.isoformat()}")

    body = (message.content or "").strip()
    if body:
        parts.append("")
        parts.append(body)

    return "\n".join(parts).strip()


def preprocess_mailing_list_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Build Pinecone sync documents for mailing-list messages.

    Args:
        failed_ids: Previous-run failed source IDs (we store/retry msg_id values).
        final_sync_at: Last sync timestamp for incremental sync; None means first sync.

    Returns:
        (documents, is_chunked)
        - documents: list[{"content": str, "metadata": dict}]
        - is_chunked: False (whole docs; ingestion pipeline may chunk later)
    """
    normalized_failed = _normalize_failed_ids(failed_ids or [])

    queryset = MailingListMessage._default_manager.select_related("sender__identity")
    if final_sync_at is None and not normalized_failed:
        candidates = queryset.order_by("id")
    else:
        criteria = Q()
        if final_sync_at is not None:
            # created_at tracks DB ingestion time, which is safer for incremental sync
            # than sent_at (historical imports can have old sent_at values).
            criteria |= Q(created_at__gt=final_sync_at)
        if normalized_failed:
            criteria |= Q(msg_id__in=normalized_failed)
        candidates = queryset.filter(criteria).order_by("id")

    docs: list[dict[str, Any]] = []
    seen_msg_ids: set[str] = set()
    for message in candidates:
        msg_id = (message.msg_id or "").strip()
        if not msg_id or msg_id in seen_msg_ids:
            continue
        seen_msg_ids.add(msg_id)

        content = _build_document_content(message)
        if not content:
            # Skip unusable empty docs; pipeline also validates chunks.
            continue

        sender_name = _get_sender_display_name(message.sender)

        safe_timestamp = int(message.sent_at.timestamp()) if message.sent_at else 0
        metadata: dict[str, Any] = {
            "doc_id": msg_id,
            "type": "mailing",
            "thread_id": message.thread_id or "",
            "subject": message.subject or "",
            "author": sender_name,
            "timestamp": safe_timestamp,
            "parent_id": message.parent_id or "",
            "source_ids": str(message.pk),
            "list_name": message.list_name or "",
        }

        docs.append({"content": content, "metadata": metadata})

    return docs, False
