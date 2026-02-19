"""
Main entry point for Pinecone sync.

Other apps call ``sync_to_pinecone()`` to push their data into Pinecone.
This module orchestrates the full flow:

1. Collect failed IDs and last sync timestamp from the database.
2. Call the caller-provided preprocessing function to get documents.
3. Upsert documents to Pinecone via PineconeIngestion.
4. Update the fail list and sync status in the database.

See docs/pinecone_sync.md for the full specification.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from . import services
from .ingestion import PineconeIngestion

logger = logging.getLogger(__name__)

# Module-level singleton; created on first use so that Django settings are
# available and Pinecone libraries are imported only when needed.
_ingestion: Optional[PineconeIngestion] = None


def _get_ingestion() -> PineconeIngestion:
    """Return (and lazily create) the module-level PineconeIngestion instance."""
    global _ingestion
    if _ingestion is None:
        _ingestion = PineconeIngestion()
    return _ingestion


# Type alias for the preprocessing function that callers must supply.
# Signature: (failed_ids: list[str], final_sync_at: datetime | None) -> tuple[list[dict], bool]
PreprocessFn = Callable[
    [list[str], Optional[datetime]], tuple[list[dict[str, Any]], bool]
]


def _empty_sync_result() -> dict[str, Any]:
    """Return the standard empty sync result dict."""
    return {
        "upserted": 0,
        "total": 0,
        "failed_count": 0,
        "failed_ids": [],
        "errors": [],
    }


def _build_documents_from_raw(raw_documents: list[dict[str, Any]]) -> list[Any]:
    """Convert preprocess output to langchain Documents; skip items missing doc_id/url."""
    from langchain_core.documents import Document

    documents: list[Any] = []
    for item in raw_documents:
        content = item.get("content", "")
        metadata = dict(item.get("metadata") or {})
        ids_str = metadata.get("ids") or item.get("ids", "") or ""

        if "doc_id" not in metadata and "url" not in metadata:
            logger.warning(
                "Skipping document with ids=%s: metadata must contain 'doc_id' or 'url'",
                ids_str,
            )
            continue

        metadata["table_ids"] = ids_str
        documents.append(Document(page_content=content, metadata=metadata))
    return documents


def _extract_new_failed_ids(result: dict[str, Any]) -> list[str]:
    """Collect source IDs from failed_documents in the upsert result."""
    new_failed_ids: list[str] = []
    for failed_doc in result.get("failed_documents", []):
        ids_str = failed_doc.get("ids", "")
        if ids_str:
            new_failed_ids.extend(
                fid.strip() for fid in ids_str.split(",") if fid.strip()
            )
    return new_failed_ids


def sync_to_pinecone(
    app_id: int,
    namespace: str,
    preprocess_fn: PreprocessFn,
) -> dict[str, Any]:
    """Run a full Pinecone sync cycle for *app_id*.

    This is the **public API** that other apps call.

    Args:
        app_id: Identifies the data source (e.g. 1, 2, 3). Stored as str(app_id) in
            PineconeFailList and PineconeSyncStatus.
        namespace: Pinecone namespace to upsert into.
        preprocess_fn: A callable returning ``(list[dict], is_chunked)``. Each dict
            must have ``content`` and ``metadata``; ``metadata`` must contain
            ``doc_id`` or ``url``. See docs/Pinecone_preprocess_guideline.md.

    Returns:
        dict with keys: upserted, total, failed_count, failed_ids, errors.
    """
    sync_type = str(app_id)
    logger.info("sync_to_pinecone: starting app_id=%s namespace=%s", app_id, namespace)

    failed_ids = services.get_failed_ids(sync_type)
    final_sync_at = services.get_final_sync_at(sync_type)
    logger.debug(
        "app_id=%s: %d previously failed IDs, final_sync_at=%s",
        app_id,
        len(failed_ids),
        final_sync_at,
    )

    raw_documents, is_chunked = preprocess_fn(failed_ids, final_sync_at)
    if not raw_documents:
        logger.info(
            "sync_to_pinecone: preprocess returned 0 documents for app_id=%s", app_id
        )
        services.update_sync_status(sync_type)
        return _empty_sync_result()

    documents = _build_documents_from_raw(raw_documents)
    if not documents:
        services.update_sync_status(sync_type)
        return _empty_sync_result()

    ingestion = _get_ingestion()
    result = ingestion.upsert_documents(
        documents, namespace=namespace, is_chunked=is_chunked
    )

    services.clear_failed_ids(sync_type)
    new_failed_ids = _extract_new_failed_ids(result)
    if new_failed_ids:
        services.record_failed_ids(sync_type, new_failed_ids)
        logger.warning(
            "app_id=%s: %d source IDs recorded as failed", app_id, len(new_failed_ids)
        )

    services.update_sync_status(sync_type)

    summary = {
        "upserted": result.get("upserted", 0),
        "total": result.get("total", 0),
        "failed_count": len(result.get("failed_documents", [])),
        "failed_ids": new_failed_ids,
        "errors": result.get("errors", []),
    }
    logger.info(
        "sync_to_pinecone: app_id=%s finished — upserted=%d, total=%d, failed=%d",
        app_id,
        summary["upserted"],
        summary["total"],
        summary["failed_count"],
    )
    return summary
