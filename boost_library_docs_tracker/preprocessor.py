"""
Preprocessor for boost_library_docs_tracker Pinecone sync.

Called by cppa_pinecone_sync.sync.sync_to_pinecone as the preprocess_fn argument.
Signature matches the PreprocessFn contract:
    (failed_ids: list[str], final_sync_at: datetime | None)
        -> tuple[list[dict], bool]
        OR tuple[list[dict], bool, list[dict]]   (with metadata updates)

The failed_ids values come from failed_documents[*]["ids"] in the upsert result,
which are BoostDocContent PKs encoded as strings.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .models import BoostDocContent
from . import workspace

logger = logging.getLogger(__name__)


def preprocess_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Build documents for Pinecone upsert from BoostDocContent records.

    Selects BoostDocContent records where is_upserted=False (not yet synced)
    or whose PK is in failed_ids (retry after a previous failure).
    final_sync_at is accepted for interface compatibility but is not used —
    is_upserted is the authoritative sync state.

    For each selected record:
      - Resolves first_version / last_version from the FK fields on BoostDocContent.
      - Loads page content from the workspace file.
      - Returns source ids in metadata["ids"] so the caller can mark
        BoostDocContent.is_upserted=True only after a successful Pinecone upsert.

    Returns (documents, is_chunked=False).
    doc_id in metadata is the content_hash of the BoostDocContent row.
    """
    records = _select_records(failed_ids, final_sync_at)
    if not records:
        return [], False

    documents, _ids_to_mark = _build_documents(records)
    return documents, False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_records(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> list[BoostDocContent]:
    """Return BoostDocContent records to process.

    Selects rows that are not yet upserted (is_upserted=False) or are in
    failed_ids for retry. The final_sync_at parameter is accepted for interface
    compatibility but is not used — is_upserted is the authoritative sync state.
    """
    from django.db.models import Q

    int_failed_ids = _parse_int_ids(failed_ids)
    query = Q(is_upserted=False)
    if int_failed_ids:
        query |= Q(pk__in=int_failed_ids)

    qs = (
        BoostDocContent.objects.filter(query)
        .select_related("first_version", "last_version")
        .order_by("id")
    )
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

        library_name = _get_library_name(doc_content)

        documents.append(
            {
                "content": page_content,
                "metadata": {
                    "doc_id": doc_content.content_hash,
                    "url": doc_content.url,
                    "first_version": first_version_str,
                    "last_version": last_version_str,
                    "library_name": library_name,
                    "ids": str(doc_content.pk),
                },
            }
        )
        ids_to_mark.append(doc_content.pk)

    return documents, ids_to_mark
