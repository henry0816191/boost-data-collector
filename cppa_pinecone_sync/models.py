"""
Models per docs/Schema.md section 9: CPPA Pinecone Sync.

PineconeFailList  – records failed sync operations by failed_id and app_id for retry or audit.
PineconeSyncStatus – tracks the last successful sync per source app_id.
"""

from django.db import models


class PineconeFailList(models.Model):
    """Records failed sync operations by failed_id and app_id for retry or audit."""

    failed_id = models.CharField(max_length=255, db_index=True)
    app_id = models.IntegerField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cppa_pinecone_sync_pineconefaillist"
        ordering = ["id"]
        verbose_name = "Pinecone fail list entry"
        verbose_name_plural = "Pinecone fail list entries"

    def __str__(self) -> str:
        return f"PineconeFailList(app_id={self.app_id}, failed_id={self.failed_id})"


class PineconeSyncStatus(models.Model):
    """Tracks the last successful sync per source app_id.

    One row per app_id (e.g. 1, 2, 3).
    final_sync_at is when the last sync for that app_id completed.
    """

    app_id = models.IntegerField(unique=True, db_index=True)
    final_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cppa_pinecone_sync_pineconesyncstatus"
        ordering = ["app_id"]
        verbose_name = "Pinecone sync status"
        verbose_name_plural = "Pinecone sync statuses"

    def __str__(self) -> str:
        return f"PineconeSyncStatus(app_id={self.app_id}, final_sync_at={self.final_sync_at})"
