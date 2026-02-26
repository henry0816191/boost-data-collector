"""Tests for cppa_pinecone_sync.services."""

import pytest
from django.utils import timezone

from cppa_pinecone_sync import services
from cppa_pinecone_sync.models import PineconeFailList, PineconeSyncStatus


# --- get_failed_ids ---


@pytest.mark.django_db
def test_get_failed_ids_empty(app_id):
    """get_failed_ids returns empty list when no records for app_id."""
    result = services.get_failed_ids(app_id)
    assert result == []


@pytest.mark.django_db
def test_get_failed_ids_returns_all_for_app_id(app_id):
    """get_failed_ids returns all failed_id values for the given app_id."""
    services.record_failed_ids(app_id, ["id1", "id2"])
    result = services.get_failed_ids(app_id)
    assert set(result) == {"id1", "id2"}


@pytest.mark.django_db
def test_get_failed_ids_filters_by_app_id(app_id):
    """get_failed_ids returns only IDs for the specified app_id."""
    services.record_failed_ids(app_id, ["a", "b"])
    services.record_failed_ids(999, ["c"])
    result = services.get_failed_ids(app_id)
    assert set(result) == {"a", "b"}


# --- clear_failed_ids ---


@pytest.mark.django_db
def test_clear_failed_ids_returns_zero_when_none(app_id):
    """clear_failed_ids returns 0 when no records for app_id."""
    count = services.clear_failed_ids(app_id)
    assert count == 0


@pytest.mark.django_db
def test_clear_failed_ids_deletes_all_for_app_id(app_id):
    """clear_failed_ids deletes all PineconeFailList records for app_id."""
    services.record_failed_ids(app_id, ["x", "y"])
    count = services.clear_failed_ids(app_id)
    assert count == 2
    assert services.get_failed_ids(app_id) == []


@pytest.mark.django_db
def test_clear_failed_ids_leaves_other_app_ids(app_id):
    """clear_failed_ids does not delete records for other app_ids."""
    services.record_failed_ids(app_id, ["a"])
    services.record_failed_ids(999, ["b"])
    services.clear_failed_ids(app_id)
    assert services.get_failed_ids(999) == ["b"]


# --- record_failed_ids ---


@pytest.mark.django_db
def test_record_failed_ids_empty_list_returns_empty(app_id):
    """record_failed_ids with empty list returns [] and creates nothing."""
    result = services.record_failed_ids(app_id, [])
    assert result == []
    assert PineconeFailList.objects.filter(app_id=app_id).count() == 0


@pytest.mark.django_db
def test_record_failed_ids_creates_entries(app_id, failed_id_list):
    """record_failed_ids bulk-creates one entry per failed_id."""
    result = services.record_failed_ids(app_id, failed_id_list)
    assert len(result) == 3
    assert all(obj.app_id == app_id for obj in result)
    ids = [obj.failed_id for obj in result]
    assert set(ids) == {"id1", "id2", "id3"}


@pytest.mark.django_db
def test_record_failed_ids_single_id(app_id):
    """record_failed_ids works with a single id."""
    result = services.record_failed_ids(app_id, ["only"])
    assert len(result) == 1
    assert result[0].failed_id == "only"


# --- get_final_sync_at ---


@pytest.mark.django_db
def test_get_final_sync_at_none_when_no_record(app_id):
    """get_final_sync_at returns None when no PineconeSyncStatus for app_id."""
    result = services.get_final_sync_at(app_id)
    assert result is None


@pytest.mark.django_db
def test_get_final_sync_at_returns_value(app_id):
    """get_final_sync_at returns final_sync_at when record exists."""
    when = timezone.now()
    services.update_sync_status(app_id, final_sync_at=when)
    result = services.get_final_sync_at(app_id)
    assert result is not None
    assert abs((result - when).total_seconds()) < 1


# --- update_sync_status ---


@pytest.mark.django_db
def test_update_sync_status_creates_new(app_id):
    """update_sync_status creates new PineconeSyncStatus and returns it."""
    when = timezone.now()
    obj = services.update_sync_status(app_id, final_sync_at=when)
    assert obj.app_id == app_id
    assert obj.final_sync_at is not None
    assert PineconeSyncStatus.objects.filter(app_id=app_id).count() == 1


@pytest.mark.django_db
def test_update_sync_status_uses_now_when_none(app_id):
    """update_sync_status uses timezone.now() when final_sync_at is None."""
    obj = services.update_sync_status(app_id)
    assert obj.final_sync_at is not None


@pytest.mark.django_db
def test_update_sync_status_updates_existing(app_id):
    """update_sync_status updates final_sync_at when record already exists."""
    old_time = timezone.now()
    services.update_sync_status(app_id, final_sync_at=old_time)
    new_time = timezone.now()
    obj = services.update_sync_status(app_id, final_sync_at=new_time)
    obj.refresh_from_db()
    assert obj.final_sync_at >= new_time
    assert PineconeSyncStatus.objects.filter(app_id=app_id).count() == 1
