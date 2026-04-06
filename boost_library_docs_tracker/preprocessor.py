"""
Preprocessor for boost_library_docs_tracker Pinecone sync.

Called by cppa_pinecone_sync.sync.sync_to_pinecone as the preprocess_fn argument.
Signature matches the PreprocessFn contract:
    (failed_ids: list[str], final_sync_at: datetime | None)
        -> tuple[list[dict], bool, list[dict]]

The third list is metas_to_update: already-upserted rows whose scraped_at is
after final_sync_at (metadata refresh in Pinecone). Empty when final_sync_at
is None or nothing is stale.

The failed_ids values come from failed_documents[*]["ids"] in the upsert result,
which are BoostDocContent PKs encoded as strings.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.utils.boost_version_operations import encode_boost_version_string
from core.utils.text_processing import clean_text

from .models import BoostDocContent
from . import workspace

logger = logging.getLogger(__name__)


def preprocess_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
    """
    Build documents for Pinecone upsert and optional metadata updates.

    Upsert batch: BoostDocContent where is_upserted=False or PK is in failed_ids
    (retry). Loads page text from the workspace for each row.

    Metadata batch (metas_to_update): when final_sync_at is set, rows with
    is_upserted=True and scraped_at > final_sync_at (re-scraped after last sync),
    excluding failed_ids. Same document shape as the upsert batch so
    ingestion.update_documents can refresh metadata; doc_id remains content_hash.

    When final_sync_at is None, metas_to_update is always [] (no incremental
    stale-metadata pass).

    Returns (documents, is_chunked=False, metas_to_update).
    """
    int_failed_ids = _parse_int_ids(failed_ids)
    upsert_records = _select_upsert_records(int_failed_ids)
    meta_records = _select_metadata_update_records(int_failed_ids, final_sync_at)

    if not upsert_records and not meta_records:
        return [], False, []

    documents, _ = _build_documents(upsert_records)
    metas_to_update, _ = _build_documents(meta_records)
    return documents, False, metas_to_update


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_upsert_records(int_failed_ids: list[int]) -> list[BoostDocContent]:
    """Rows to vector-upsert: not yet upserted or explicitly failed (retry)."""
    from django.db.models import Q

    query = Q(is_upserted=False)
    if int_failed_ids:
        query |= Q(pk__in=int_failed_ids)

    qs = (
        BoostDocContent.objects.filter(query)
        .select_related("first_version", "last_version")
        .order_by("id")
    )
    return list(qs)


def _select_metadata_update_records(
    int_failed_ids: list[int],
    final_sync_at: datetime | None,
) -> list[BoostDocContent]:
    """Rows needing Pinecone metadata refresh only (already upserted, scraped since sync)."""
    if final_sync_at is None:
        return []

    qs = (
        BoostDocContent.objects.filter(
            is_upserted=True,
            scraped_at__gt=final_sync_at,
        )
        .select_related("first_version", "last_version")
        .order_by("id")
    )
    if int_failed_ids:
        qs = qs.exclude(pk__in=int_failed_ids)
    return list(qs)


def _parse_int_ids(failed_ids: list[str]) -> list[int]:
    """Convert string IDs to ints, skipping malformed values.

    Each entry in failed_ids may itself be a comma-separated string of PKs
    because cppa_pinecone_sync stores them as "42,43" in failed_documents[*]["ids"].
    """
    result = []
    for fid in failed_ids:
        for token in str(fid).split(","):
            token = token.strip()
            if not token:
                continue
            try:
                result.append(int(token))
            except (ValueError, TypeError):
                logger.warning("Skipping non-integer failed_id token: %r", token)
    return result


def _get_library_name(doc_content: BoostDocContent) -> str:
    """
    Derive the library name from the most recently created documentation relation.

    A BoostDocContent row can be linked to multiple library/version rows over time,
    so use the latest BoostLibraryDocumentation relation for the best current match.
    Returns an empty string if no relation is found.
    """
    rel = (
        doc_content.library_relations.select_related("boost_library_version__library")
        .order_by("-created_at", "-id")
        .first()
    )
    if rel is None:
        return ""
    return rel.boost_library_version.library.name


def _build_documents(
    records: list[BoostDocContent],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Build raw document dicts and return source ids selected for upsert."""
    documents: list[dict[str, Any]] = []
    ids_to_mark: list[int] = []

    for doc_content in records:
        first_version_str = (
            doc_content.first_version.version if doc_content.first_version else ""
        )
        last_version_str = (
            doc_content.last_version.version if doc_content.last_version else ""
        )

        page_content = workspace.load_page_by_url(doc_content.url)
        if page_content is None:
            logger.warning(
                "Workspace file missing for url=%s (doc_content_id=%d), skipping.",
                doc_content.url,
                doc_content.pk,
            )
            continue

        page_content = clean_text(page_content, remove_extra_spaces=False)

        library_name = _get_library_name(doc_content)

        metadata: dict[str, Any] = {
            "doc_id": doc_content.content_hash,
            "url": doc_content.url,
            "library_name": library_name,
            "source_ids": str(doc_content.pk),
        }
        fk = encode_boost_version_string(first_version_str)
        if fk is not None:
            metadata["first_version_key"] = fk
        lk = encode_boost_version_string(last_version_str)
        if lk is not None:
            metadata["last_version_key"] = lk

        documents.append(
            {
                "content": page_content,
                "metadata": metadata,
            }
        )
        ids_to_mark.append(doc_content.pk)

    return documents, ids_to_mark
