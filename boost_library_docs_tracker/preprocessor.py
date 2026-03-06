"""
Preprocessor for boost_library_docs_tracker Pinecone sync.

Called by cppa_pinecone_sync.sync.sync_to_pinecone as the preprocess_fn argument.
Signature matches the PreprocessFn contract:
    (failed_ids: list[str], final_sync_at: datetime | None)
        -> tuple[list[dict], bool]
        OR tuple[list[dict], bool, list[dict]]   (with metadata updates)

The failed_ids values come from failed_documents[*]["ids"] in the upsert result,
which are comma-separated strings of BoostLibraryDocumentation PKs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from boost_library_tracker.models import BoostVersion

from .models import BoostDocContent, BoostLibraryDocumentation
from . import services, workspace

logger = logging.getLogger(__name__)


def preprocess_for_pinecone(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Build documents for Pinecone upsert from BoostLibraryDocumentation records.

    Selects records that:
      - have id in failed_ids (retry), OR
      - were created after final_sync_at (incremental sync).

    For each selected record:
      - Resolves first_version / last_version via BoostVersion.version_created_at ordering.
      - Skips if current_version is older than last_version (not the latest holder).
      - Skips if current_version == last_version and is_upserted is True (already synced).
      - Loads page_content from the workspace file.
      - Marks the BoostLibraryDocumentation row as is_upserted=True before returning.

    Returns (documents, is_chunked=False).
    doc_id in metadata is the content_hash of the BoostDocContent row.
    """
    records = _select_records(failed_ids, final_sync_at)
    if not records:
        return [], False

    version_order = _build_version_order()
    documents = _build_documents(records, version_order)
    return documents, False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_records(
    failed_ids: list[str],
    final_sync_at: datetime | None,
) -> list[BoostLibraryDocumentation]:
    """Return deduplicated BoostLibraryDocumentation records to process."""
    from django.db.models import Q

    int_failed_ids = _parse_int_ids(failed_ids)
    query = Q(pk__in=int_failed_ids)
    if final_sync_at is not None:
        query |= Q(created_at__gt=final_sync_at)
    else:
        query = Q()  # first run: include all

    qs = (
        BoostLibraryDocumentation.objects.filter(query)
        .select_related(
            "boost_doc_content",
            "boost_library_version__version",
            "boost_library_version__library",
        )
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


def _build_version_order() -> dict[int, int]:
    """
    Return a mapping of BoostVersion.pk → sort_order (0 = oldest).
    Versions without version_created_at are sorted last by version string.
    """
    versions = list(
        BoostVersion.objects.all().values("pk", "version", "version_created_at")
    )
    versions.sort(
        key=lambda v: (
            v["version_created_at"] is None,
            v["version_created_at"] or "",
            v["version"],
        )
    )
    return {v["pk"]: idx for idx, v in enumerate(versions)}


def _get_version_range(
    doc_content: BoostDocContent,
    version_order: dict[int, int],
) -> tuple[str, str, int | None]:
    """
    For the given BoostDocContent, determine first_version, last_version,
    and the version_id of the last (newest) version.

    Returns (first_version_str, last_version_str, last_version_id).
    """
    relations = list(
        BoostLibraryDocumentation.objects.filter(
            boost_doc_content=doc_content,
        ).select_related("boost_library_version__version")
    )

    if not relations:
        return "", "", None

    def _order_key(rel: BoostLibraryDocumentation) -> int:
        ver_id = rel.boost_library_version.version_id
        return version_order.get(ver_id, 999_999)

    relations.sort(key=_order_key)
    first_rel = relations[0]
    last_rel = relations[-1]
    first_version = first_rel.boost_library_version.version.version
    last_version = last_rel.boost_library_version.version.version
    last_version_id = last_rel.boost_library_version.version_id
    return first_version, last_version, last_version_id


def _build_documents(
    records: list[BoostLibraryDocumentation],
    version_order: dict[int, int],
) -> list[dict[str, Any]]:
    """Build raw document dicts, apply skip rules, mark rows as upserted."""
    documents: list[dict[str, Any]] = []
    ids_to_mark: list[int] = []

    for rec in records:
        doc_content = rec.boost_doc_content
        lib_ver = rec.boost_library_version

        first_version, last_version, last_version_id = _get_version_range(
            doc_content, version_order
        )
        if not last_version_id:
            logger.warning(
                "No version range found for BoostDocContent id=%d, skipping.",
                doc_content.pk,
            )
            continue

        current_version_id = lib_ver.version_id
        current_order = version_order.get(current_version_id, 999_999)
        last_order = version_order.get(last_version_id, 999_999)

        # Skip if current version is older than last version
        if current_order < last_order:
            logger.debug(
                "Skipping doc_content_id=%d: current_version_id=%d is older than last.",
                doc_content.pk,
                current_version_id,
            )
            continue

        # Skip if already upserted at the last version
        if current_order == last_order and rec.is_upserted:
            logger.debug(
                "Skipping doc_content_id=%d: already upserted at last version.",
                doc_content.pk,
            )
            continue

        page_content = workspace.load_page_by_url(doc_content.url)
        if not page_content:
            logger.warning(
                "Workspace file missing for url=%s (doc_content_id=%d), skipping.",
                doc_content.url,
                doc_content.pk,
            )
            continue

        documents.append(
            {
                "content": page_content,
                "metadata": {
                    "doc_id": doc_content.content_hash,
                    "url": doc_content.url,
                    "first_version": first_version,
                    "last_version": last_version,
                    "library_name": lib_ver.library.name,
                    "ids": str(rec.pk),
                },
            }
        )
        ids_to_mark.append(rec.pk)

    if ids_to_mark:
        services.set_is_upserted_by_ids(ids_to_mark, True)
        logger.info(
            "Marked %d BoostLibraryDocumentation rows as is_upserted=True.",
            len(ids_to_mark),
        )

    return documents
