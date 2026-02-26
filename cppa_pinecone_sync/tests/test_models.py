"""Tests for cppa_pinecone_sync models."""

import pytest
from model_bakery import baker

from cppa_pinecone_sync.models import PineconeFailList


# --- PineconeFailList ---


@pytest.mark.django_db
def test_pinecone_fail_list_creation():
    """PineconeFailList can be created with failed_id and type."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="doc-123",
        type="slack",
    )
    assert obj.id is not None
    assert obj.failed_id == "doc-123"
    assert obj.type == "slack"
    assert obj.created_at is not None


@pytest.mark.django_db
def test_pinecone_fail_list_str():
    """PineconeFailList __str__ includes type and failed_id."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="id-456",
        type="mailing_list",
    )
    s = str(obj)
    assert "mailing_list" in s
    assert "id-456" in s


@pytest.mark.django_db
def test_pinecone_fail_list_multiple_per_type():
    """Multiple PineconeFailList entries can exist for same type."""
    baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="a",
        type="wg21",
    )
    baker.make(
        "cppa_pinecone_sync.PineconeFailList",
        failed_id="b",
        type="wg21",
    )
    assert PineconeFailList.objects.filter(type="wg21").count() == 2


# --- PineconeSyncStatus ---


@pytest.mark.django_db
def test_pinecone_sync_status_creation():
    """PineconeSyncStatus can be created with type and optional final_sync_at."""
    obj = baker.make(
        "cppa_pinecone_sync.PineconeSyncStatus",
        type="slack",
        final_sync_at=None,
    )
    assert obj.id is not None
    assert obj.type == "slack"
    assert obj.final_sync_at is None
    assert obj.created_at is not None
    assert obj.updated_at is not None


@pytest.mark.django_db
def test_pinecone_sync_status_str():
    """PineconeSyncStatus __str__ includes type and final_sync_at."""
    from django.utils import timezone

    when = timezone.now()
    obj = baker.make(
        "cppa_pinecone_sync.PineconeSyncStatus",
        type="slack",
        final_sync_at=when,
    )
    s = str(obj)
    assert "slack" in s


@pytest.mark.django_db
def test_pinecone_sync_status_type_unique():
    """PineconeSyncStatus type is unique."""
    from django.db import IntegrityError

    baker.make("cppa_pinecone_sync.PineconeSyncStatus", type="unique_type")
    with pytest.raises(IntegrityError):
        baker.make("cppa_pinecone_sync.PineconeSyncStatus", type="unique_type")
