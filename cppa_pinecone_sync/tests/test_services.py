"""Tests for cppa_pinecone_sync.services."""

import pytest
from django.utils import timezone

from cppa_pinecone_sync import services
from cppa_pinecone_sync.models import PineconeFailList, PineconeSyncStatus


# --- get_failed_ids ---


@pytest.mark.django_db
def test_get_failed_ids_empty(app_type):
    """get_failed_ids returns empty list when no records for app_type."""
    result = services.get_failed_ids(app_type)
    assert result == []


@pytest.mark.django_db
def test_get_failed_ids_returns_all_for_app_type(app_type):
    """get_failed_ids returns all failed_id values for the given app_type."""
    services.record_failed_ids(app_type, ["id1", "id2"])
    result = services.get_failed_ids(app_type)
    assert set(result) == {"id1", "id2"}


@pytest.mark.django_db
def test_get_failed_ids_filters_by_app_type(app_type):
    """get_failed_ids returns only IDs for the specified app_type."""
    services.record_failed_ids(app_type, ["a", "b"])
    services.record_failed_ids("mailing", ["c"])
    result = services.get_failed_ids(app_type)
    assert set(result) == {"a", "b"}


# --- clear_failed_ids ---


@pytest.mark.django_db
def test_clear_failed_ids_returns_zero_when_none(app_type):
    """clear_failed_ids returns 0 when no records for app_type."""
    count = services.clear_failed_ids(app_type)
    assert count == 0


@pytest.mark.django_db
def test_clear_failed_ids_deletes_all_for_app_type(app_type):
    """clear_failed_ids deletes all PineconeFailList records for app_type."""
    services.record_failed_ids(app_type, ["x", "y"])
    count = services.clear_failed_ids(app_type)
    assert count == 2
    assert services.get_failed_ids(app_type) == []


@pytest.mark.django_db
def test_clear_failed_ids_leaves_other_app_types(app_type):
    """clear_failed_ids does not delete records for other app_types."""
    services.record_failed_ids(app_type, ["a"])
    services.record_failed_ids("mailing", ["b"])
    services.clear_failed_ids(app_type)
    assert services.get_failed_ids("mailing") == ["b"]


# --- record_failed_ids ---


@pytest.mark.django_db
def test_record_failed_ids_empty_list_returns_empty(app_type):
    """record_failed_ids with empty list returns [] and creates nothing."""
    result = services.record_failed_ids(app_type, [])
    assert result == []
    assert PineconeFailList.objects.filter(app_type=app_type).count() == 0


@pytest.mark.django_db
def test_record_failed_ids_creates_entries(app_type, failed_id_list):
    """record_failed_ids bulk-creates one entry per failed_id."""
    result = services.record_failed_ids(app_type, failed_id_list)
    assert len(result) == 3
    assert all(obj.app_type == app_type for obj in result)
    ids = [obj.failed_id for obj in result]
    assert set(ids) == {"id1", "id2", "id3"}


@pytest.mark.django_db
def test_record_failed_ids_single_id(app_type):
    """record_failed_ids works with a single id."""
    result = services.record_failed_ids(app_type, ["only"])
    assert len(result) == 1
    assert result[0].failed_id == "only"


# --- get_final_sync_at ---


@pytest.mark.django_db
def test_get_final_sync_at_none_when_no_record(app_type):
    """get_final_sync_at returns None when no PineconeSyncStatus for app_type."""
    result = services.get_final_sync_at(app_type)
    assert result is None


@pytest.mark.django_db
def test_get_final_sync_at_returns_value(app_type):
    """get_final_sync_at returns final_sync_at when record exists."""
    when = timezone.now()
    services.update_sync_status(app_type, final_sync_at=when)
    result = services.get_final_sync_at(app_type)
    assert result is not None
    assert abs((result - when).total_seconds()) < 1


# --- update_sync_status ---


@pytest.mark.django_db
def test_update_sync_status_creates_new(app_type):
    """update_sync_status creates new PineconeSyncStatus and returns it."""
    when = timezone.now()
    obj = services.update_sync_status(app_type, final_sync_at=when)
    assert obj.app_type == app_type
    assert obj.final_sync_at is not None
    assert PineconeSyncStatus.objects.filter(app_type=app_type).count() == 1


@pytest.mark.django_db
def test_update_sync_status_uses_now_when_none(app_type):
    """update_sync_status uses timezone.now() when final_sync_at is None."""
    obj = services.update_sync_status(app_type)
    assert obj.final_sync_at is not None


@pytest.mark.django_db
def test_update_sync_status_updates_existing(app_type):
    """update_sync_status updates final_sync_at when record already exists."""
    old_time = timezone.now()
    services.update_sync_status(app_type, final_sync_at=old_time)
    new_time = timezone.now()
    obj = services.update_sync_status(app_type, final_sync_at=new_time)
    obj.refresh_from_db()
    assert obj.final_sync_at >= new_time
    assert PineconeSyncStatus.objects.filter(app_type=app_type).count() == 1
