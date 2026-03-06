"""
Service layer for cppa_pinecone_sync.

All creates/updates/deletes for this app's models must go through functions in this
module. Do not call Model.objects.create(), model.save(), or model.delete() from
outside this module (e.g. from management commands, views, or other apps).

See docs/Contributing.md for the project-wide rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.utils import timezone

from .models import PineconeFailList, PineconeSyncStatus


# --- PineconeFailList ---


def get_failed_ids(app_type: str) -> list[str]:
    """Return all failed_id values for the given app_type."""
    return list(
        PineconeFailList.objects.filter(app_type=app_type).values_list(
            "failed_id", flat=True
        )
    )


def clear_failed_ids(app_type: str) -> int:
    """Delete all PineconeFailList records for the given app_type. Returns count deleted."""
    count, _ = PineconeFailList.objects.filter(app_type=app_type).delete()
    return count


def record_failed_ids(app_type: str, failed_ids: list[str]) -> list[PineconeFailList]:
    """Bulk-create PineconeFailList entries for each failed_id. Returns created objects."""
    if not failed_ids:
        return []
    objs = [PineconeFailList(failed_id=fid, app_type=app_type) for fid in failed_ids]
    return PineconeFailList.objects.bulk_create(objs)


# --- PineconeSyncStatus ---


def get_final_sync_at(app_type: str) -> Optional[datetime]:
    """Return final_sync_at for the given app_type, or None if no record exists."""
    row = PineconeSyncStatus.objects.filter(app_type=app_type).first()
    return row.final_sync_at if row else None


def update_sync_status(
    app_type: str, final_sync_at: Optional[datetime] = None
) -> PineconeSyncStatus:
    """Create or update PineconeSyncStatus for the given app_type.

    Sets final_sync_at to the provided value, or now() if not given.
    Returns the PineconeSyncStatus instance.
    """
    ts = final_sync_at or timezone.now()
    obj, created = PineconeSyncStatus.objects.get_or_create(
        app_type=app_type,
        defaults={"final_sync_at": ts},
    )
    if not created:
        obj.final_sync_at = ts
        obj.save(update_fields=["final_sync_at", "updated_at"])
    return obj
