"""
Service layer for boost_library_docs_tracker.
All DB writes to boost_library_docs_tracker models go through this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import BoostDocContent, BoostLibraryDocumentation

if TYPE_CHECKING:
    from django.db import models as django_models


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# BoostDocContent
# ---------------------------------------------------------------------------


def get_or_create_doc_content(
    url: str,
    content_hash: str,
    version_id: int | None = None,
) -> tuple[BoostDocContent, str]:
    """
    Get or create a BoostDocContent row for the given content_hash.
    Page content is NOT stored in the DB; it lives in workspace files.

    version_id is the PK of the BoostVersion being processed. When provided:
      - On create: sets both first_version and last_version to version_id.
      - On update: updates last_version to version_id.

    Returns (doc_content, change_type) where change_type is one of:
      "created"    — content_hash was not in DB; row inserted.
      "unchanged"  — content_hash already existed; row may still be updated
        (url, scraped_at, last_version / first_version as applicable). The document
        body identity is the same hash, not a new page.

    Raises ValueError if url is empty.
    """
    normalized_url = url.strip()
    if not normalized_url:
        raise ValueError("url must not be empty")

    now = _now()
    try:
        obj = BoostDocContent.objects.get(content_hash=content_hash)
    except BoostDocContent.DoesNotExist:
        create_kwargs: dict = {
            "url": normalized_url,
            "content_hash": content_hash,
            "scraped_at": now,
            "is_upserted": False,
        }
        if version_id is not None:
            create_kwargs["first_version_id"] = version_id
            create_kwargs["last_version_id"] = version_id
        obj = BoostDocContent.objects.create(**create_kwargs)
        return obj, "created"

    update_fields = ["scraped_at"]
    change_type = "unchanged"

    if obj.url != normalized_url:
        obj.url = normalized_url
        update_fields.append("url")

    if version_id is not None:
        obj.last_version_id = version_id
        update_fields.append("last_version_id")
        if obj.first_version_id is None:
            obj.first_version_id = version_id
            update_fields.append("first_version_id")

    obj.scraped_at = now
    obj.save(update_fields=update_fields)
    return obj, change_type


def set_doc_content_upserted(
    doc: BoostDocContent,
    value: bool,
) -> BoostDocContent:
    """Set is_upserted on a BoostDocContent row."""
    doc.is_upserted = value
    doc.save(update_fields=["is_upserted"])
    return doc


def set_doc_content_upserted_by_ids(
    ids: list[int],
    value: bool,
) -> int:
    """
    Bulk-set is_upserted for BoostDocContent rows with the given PKs.
    Returns the number of rows updated.
    """
    if not ids:
        return 0
    return BoostDocContent.objects.filter(pk__in=ids).update(is_upserted=value)


def get_unupserted_doc_contents() -> django_models.QuerySet:
    """Return all BoostDocContent rows that have not been upserted to Pinecone."""
    return BoostDocContent.objects.filter(is_upserted=False)


# ---------------------------------------------------------------------------
# BoostLibraryDocumentation
# ---------------------------------------------------------------------------


def link_content_to_library_version(
    library_version_id: int,
    doc_content_id: int,
) -> tuple[BoostLibraryDocumentation, bool]:
    """
    Get or create a BoostLibraryDocumentation row for the (library_version, doc_content) pair.
    Returns (relation, created).
    """
    obj, created = BoostLibraryDocumentation.objects.get_or_create(
        boost_library_version_id=library_version_id,
        boost_doc_content_id=doc_content_id,
    )
    return obj, created


def get_docs_for_library_version(
    library_version_id: int,
) -> django_models.QuerySet:
    """Return all BoostLibraryDocumentation rows for this library-version."""
    return BoostLibraryDocumentation.objects.filter(
        boost_library_version_id=library_version_id,
    )
