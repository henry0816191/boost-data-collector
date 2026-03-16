"""Tests for cppa_pinecone_sync models."""

import pytest
from model_bakery import baker

from cppa_pinecone_sync.models import PineconeFailList


# --- PineconeFailList ---


@pytest.mark.django_db
def test_pinecone_fail_list_creation():
    """PineconeFailList can be created with failed_id and app_type."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="doc-123",
        app_type="slack",
    )
    assert obj.id is not None
    assert obj.failed_id == "doc-123"
    assert obj.app_type == "slack"
    assert obj.created_at is not None


@pytest.mark.django_db
def test_pinecone_fail_list_str():
    """PineconeFailList __str__ includes app_type and failed_id."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="id-456",
        app_type="mailing",
    )
    s = str(obj)
    assert "mailing" in s
    assert "id-456" in s


@pytest.mark.django_db
def test_pinecone_fail_list_multiple_per_app_type():
    """Multiple PineconeFailList entries can exist for the same app_type."""
    baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="a",
        app_type="slack",
    )
    baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="b",
        app_type="slack",
    )
    assert PineconeFailList.objects.filter(app_type="slack").count() == 2


# --- PineconeSyncStatus ---


@pytest.mark.django_db
def test_pinecone_sync_status_creation():
    """PineconeSyncStatus can be created with app_type and optional final_sync_at."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeSyncStatus",
        app_type="slack",
        final_sync_at=None,
    )
    assert obj.id is not None
    assert obj.app_type == "slack"
    assert obj.final_sync_at is None
    assert obj.created_at is not None
    assert obj.updated_at is not None


@pytest.mark.django_db
def test_pinecone_sync_status_str():
    """PineconeSyncStatus __str__ includes app_type and final_sync_at."""
    from django.utils import timezone

    when = timezone.now()
    obj = baker.make(
        "cppa_pinecone_sync.PineconeSyncStatus",
        app_type="slack",
        final_sync_at=when,
    )
    s = str(obj)
    assert "slack" in s
    assert "final_sync_at" in s


@pytest.mark.django_db
def test_pinecone_sync_status_app_type_unique():
    """PineconeSyncStatus app_type is unique."""
    from django.db import IntegrityError

    baker.make("cppa_pinecone_sync.PineconeSyncStatus", app_type="mailing")
    with pytest.raises(IntegrityError):
        baker.make("cppa_pinecone_sync.PineconeSyncStatus", app_type="mailing")
