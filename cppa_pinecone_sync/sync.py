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


from django.db import transaction


from . import services

from .ingestion import PineconeIngestion, PineconeInstance


logger = logging.getLogger(__name__)


# Module-level singletons keyed by instance; created on first use so that
# Django settings are available and Pinecone libraries are imported only when
# needed.

_ingestion_pool: dict[str, PineconeIngestion] = {}


def _get_ingestion(
    instance: PineconeInstance = PineconeInstance.PUBLIC,
) -> PineconeIngestion:
    """Return (and lazily create) a PineconeIngestion for *instance*."""

    key = instance.value

    if key not in _ingestion_pool:

        _ingestion_pool[key] = PineconeIngestion(instance=instance)

    return _ingestion_pool[key]


# Type alias for the preprocessing function that callers must supply.

# Signature:

#   - legacy: (failed_ids, final_sync_at) -> (raw_documents, is_chunked)

#   - metadata update: (failed_ids, final_sync_at) -> (raw_documents, is_chunked, metas_to_update)

PreprocessFn = Callable[
    [list[str], Optional[datetime]],
    tuple[list[dict[str, Any]], bool]
    | tuple[list[dict[str, Any]], bool, list[dict[str, Any]]],
]


def _empty_sync_result() -> dict[str, Any]:
    """Return the standard empty sync result dict."""

    return {
        "upserted": 0,
        "updated": 0,
        "total": 0,
        "failed_count": 0,
        "failed_ids": [],
        "attempted_source_ids": [],
        "successful_source_ids": [],
        "errors": [],
        "update_errors": [],
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


def _extract_source_ids_from_documents(documents: list[Any]) -> list[str]:
    """

    Collect deduplicated source IDs from Document.metadata.table_ids in order.

    """

    seen: set[str] = set()

    source_ids: list[str] = []

    for doc in documents:

        table_ids = str(doc.metadata.get("table_ids", "")).strip()

        if not table_ids:

            continue

        for token in table_ids.split(","):

            source_id = token.strip()

            if not source_id or source_id in seen:

                continue

            seen.add(source_id)

            source_ids.append(source_id)

    return source_ids


def sync_to_pinecone(
    app_type: str,
    namespace: str,
    preprocess_fn: PreprocessFn,
    instance: PineconeInstance = PineconeInstance.PUBLIC,
) -> dict[str, Any]:
    """Run a full Pinecone sync cycle for *app_type*.



    This is the **public API** that other apps call.



    Args:

        app_type: Identifies the data source (e.g. "slack", "mailing"). Stored as

            CharField in

            PineconeFailList and PineconeSyncStatus.

        namespace: Pinecone namespace to upsert into.

        preprocess_fn: A callable returning ``(list[dict], is_chunked)``. Each dict

            must have ``content`` and ``metadata``; ``metadata`` must contain

            ``doc_id`` or ``url``. See docs/Pinecone_preprocess_guideline.md.

        instance: Which Pinecone API key to use (public or private).

            Default is public.



    Returns:

        dict with keys: upserted, updated, total, failed_count, failed_ids,

        errors, update_errors.

    """

    logger.info(
        "sync_to_pinecone: starting app_type=%s namespace=%s instance=%s",
        app_type,
        namespace,
        instance.value,
    )

    failed_ids = services.get_failed_ids(app_type)

    final_sync_at = services.get_final_sync_at(app_type)

    logger.debug(
        "app_type=%s: %d previously failed IDs, final_sync_at=%s",
        app_type,
        len(failed_ids),
        final_sync_at,
    )

    preprocess_result = preprocess_fn(failed_ids, final_sync_at)

    if len(preprocess_result) == 2:

        raw_documents, is_chunked = preprocess_result

        metas_to_update: list[dict[str, Any]] = []

    elif len(preprocess_result) == 3:

        raw_documents, is_chunked, metas_to_update = preprocess_result

    else:

        raise ValueError(
            "preprocess_fn must return either "
            "(raw_documents, is_chunked) or "
            "(raw_documents, is_chunked, metas_to_update)"
        )

    if not raw_documents:

        logger.info(
            "sync_to_pinecone: preprocess returned 0 documents for app_type=%s",
            app_type,
        )

        services.update_sync_status(app_type)

        return _empty_sync_result()

    documents = _build_documents_from_raw(raw_documents)

    if not documents:

        services.update_sync_status(app_type)

        return _empty_sync_result()

    attempted_source_ids = _extract_source_ids_from_documents(documents)

    ingestion = _get_ingestion(instance)

    result = ingestion.upsert_documents(
        documents=documents, namespace=namespace, is_chunked=is_chunked
    )

    update_result: dict[str, Any] = {"updated": 0, "errors": []}

    if metas_to_update:

        documents = _build_documents_from_raw(metas_to_update)

        if not documents:

            services.update_sync_status(app_type)

            return _empty_sync_result()

        update_result = ingestion.update_documents(
            documents=documents, namespace=namespace, is_chunked=is_chunked
        )

    new_failed_ids = _extract_new_failed_ids(result)

    with transaction.atomic():

        services.clear_failed_ids(app_type)

        if new_failed_ids:

            services.record_failed_ids(app_type, new_failed_ids)

        logger.warning(
            "app_type=%s: %d source IDs recorded as failed",
            app_type,
            len(new_failed_ids),
        )

    services.update_sync_status(app_type)

    failed_source_ids_set = set(new_failed_ids)

    successful_source_ids = [
        source_id
        for source_id in attempted_source_ids
        if source_id not in failed_source_ids_set
    ]

    summary = {
        "upserted": result.get("upserted", 0),
        "updated": update_result.get("updated", 0),
        "total": result.get("total", 0),
        "failed_count": len(result.get("failed_documents", [])),
        "failed_ids": new_failed_ids,
        "attempted_source_ids": attempted_source_ids,
        "successful_source_ids": successful_source_ids,
        "errors": result.get("errors", []),
        "update_errors": update_result.get("errors", []),
    }

    logger.info(
        "sync_to_pinecone: app_type=%s finished — upserted=%d, total=%d, failed=%d",
        app_type,
        summary["upserted"],
        summary["total"],
        summary["failed_count"],
    )

    return summary
