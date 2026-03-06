"""
Service layer for boost_library_docs_tracker.
All DB writes to boost_library_docs_tracker models go through this module.
See docs/service_api/boost_library_docs_tracker.md for the full API reference.
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
) -> tuple[BoostDocContent, str]:
    """
    Get or create a BoostDocContent row for the given URL.
    Page content is NOT stored in the DB; it lives in workspace files.

    Returns (doc_content, change_type) where change_type is one of:
      "created"         — URL was not in DB; row inserted.
      "content_changed" — URL exists but content_hash differs; hash updated.
      "unchanged"       — URL exists and content_hash matches; only scraped_at updated.

    Raises ValueError if url is empty.
    """
    if not url or not url.strip():
        raise ValueError("url must not be empty")

    now = _now()
    try:
        obj = BoostDocContent.objects.get(url=url)
    except BoostDocContent.DoesNotExist:
        obj = BoostDocContent.objects.create(
            url=url,
            content_hash=content_hash,
            scraped_at=now,
        )
        return obj, "created"

    if obj.content_hash != content_hash:
        obj.content_hash = content_hash
        obj.scraped_at = now
        obj.save(update_fields=["content_hash", "scraped_at"])
        return obj, "content_changed"

    obj.scraped_at = now
    obj.save(update_fields=["scraped_at"])
    return obj, "unchanged"


# ---------------------------------------------------------------------------
# BoostLibraryDocumentation
# ---------------------------------------------------------------------------


def link_content_to_library_version(
    library_version_id: int,
    doc_content_id: int,
    page_count: int,
) -> tuple[BoostLibraryDocumentation, bool]:
    """
    Get or create a BoostLibraryDocumentation row for the (library_version, doc_content) pair.
    Sets page_count. If the row exists and page_count differs, updates it.
    Returns (relation, created).
    """
    obj, created = BoostLibraryDocumentation.objects.get_or_create(
        boost_library_version_id=library_version_id,
        boost_doc_content_id=doc_content_id,
        defaults={"page_count": page_count},
    )
    if not created and obj.page_count != page_count:
        obj.page_count = page_count
        obj.save(update_fields=["page_count"])
    return obj, created


def set_is_upserted(
    doc: BoostLibraryDocumentation,
    value: bool,
) -> BoostLibraryDocumentation:
    """Set is_upserted on a BoostLibraryDocumentation row."""
    doc.is_upserted = value
    doc.save(update_fields=["is_upserted", "updated_at"])
    return doc


def set_is_upserted_by_ids(
    ids: list[int],
    value: bool,
) -> int:
    """
    Bulk-set is_upserted for BoostLibraryDocumentation rows with the given PKs.
    Returns the number of rows updated.
    """
    if not ids:
        return 0
    return BoostLibraryDocumentation.objects.filter(pk__in=ids).update(
        is_upserted=value
    )


def get_docs_for_library_version(
    library_version_id: int,
) -> django_models.QuerySet:
    """Return all BoostLibraryDocumentation rows for this library-version."""
    return BoostLibraryDocumentation.objects.filter(
        boost_library_version_id=library_version_id,
    )
