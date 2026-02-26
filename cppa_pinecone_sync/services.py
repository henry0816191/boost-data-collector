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


def get_failed_ids(app_id: int) -> list[str]:
    """Return all failed_id values for the given app_id."""
    return list(
        PineconeFailList.objects.filter(app_id=app_id).values_list(
            "failed_id", flat=True
        )
    )


def clear_failed_ids(app_id: int) -> int:
    """Delete all PineconeFailList records for the given app_id. Returns count deleted."""
    count, _ = PineconeFailList.objects.filter(app_id=app_id).delete()
    return count


def record_failed_ids(app_id: int, failed_ids: list[str]) -> list[PineconeFailList]:
    """Bulk-create PineconeFailList entries for each failed_id. Returns created objects."""
    if not failed_ids:
        return []
    objs = [PineconeFailList(failed_id=fid, app_id=app_id) for fid in failed_ids]
    return PineconeFailList.objects.bulk_create(objs)


# --- PineconeSyncStatus ---


def get_final_sync_at(app_id: int) -> Optional[datetime]:
    """Return final_sync_at for the given app_id, or None if no record exists."""
    row = PineconeSyncStatus.objects.filter(app_id=app_id).first()
    return row.final_sync_at if row else None


def update_sync_status(
    app_id: int, final_sync_at: Optional[datetime] = None
) -> PineconeSyncStatus:
    """Create or update PineconeSyncStatus for the given app_id.

    Sets final_sync_at to the provided value, or now() if not given.
    Returns the PineconeSyncStatus instance.
    """
    ts = final_sync_at or timezone.now()
    obj, created = PineconeSyncStatus.objects.get_or_create(
        app_id=app_id,
        defaults={"final_sync_at": ts},
    )
    if not created:
        obj.final_sync_at = ts
        obj.save(update_fields=["final_sync_at", "updated_at"])
    return obj
