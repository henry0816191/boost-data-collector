"""Tests for cppa_pinecone_sync models."""

import pytest
from model_bakery import baker

from cppa_pinecone_sync.models import PineconeFailList


# --- PineconeFailList ---


@pytest.mark.django_db
def test_pinecone_fail_list_creation():
    """PineconeFailList can be created with failed_id and app_id."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="doc-123",
        app_id=1,
    )
    assert obj.id is not None
    assert obj.failed_id == "doc-123"
    assert obj.app_id == 1
    assert obj.created_at is not None


@pytest.mark.django_db
def test_pinecone_fail_list_str():
    """PineconeFailList __str__ includes app_id and failed_id."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="id-456",
        app_id=2,
    )
    s = str(obj)
    assert "2" in s
    assert "id-456" in s


@pytest.mark.django_db
def test_pinecone_fail_list_multiple_per_app_id():
    """Multiple PineconeFailList entries can exist for the same app_id."""
    baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="a",
        app_id=3,
    )
    baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="b",
        app_id=3,
    )
    assert PineconeFailList.objects.filter(app_id=3).count() == 2


# --- PineconeSyncStatus ---


@pytest.mark.django_db
def test_pinecone_sync_status_creation():
    """PineconeSyncStatus can be created with app_id and optional final_sync_at."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeSyncStatus",
        app_id=1,
        final_sync_at=None,
    )
    assert obj.id is not None
    assert obj.app_id == 1
    assert obj.final_sync_at is None
    assert obj.created_at is not None
    assert obj.updated_at is not None


@pytest.mark.django_db
def test_pinecone_sync_status_str():
    """PineconeSyncStatus __str__ includes app_id and final_sync_at."""
    from django.utils import timezone

    when = timezone.now()
    obj = baker.make(
        "cppa_pinecone_sync.PineconeSyncStatus",
        app_id=1,
        final_sync_at=when,
    )
    s = str(obj)
    assert "1" in s


@pytest.mark.django_db
def test_pinecone_sync_status_app_id_unique():
    """PineconeSyncStatus app_id is unique."""
    from django.db import IntegrityError

    baker.make("cppa_pinecone_sync.PineconeSyncStatus", app_id=42)
    with pytest.raises(IntegrityError):
        baker.make("cppa_pinecone_sync.PineconeSyncStatus", app_id=42)
