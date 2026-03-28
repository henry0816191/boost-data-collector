"""Tests for cppa_pinecone_sync.sync module (helpers and sync_to_pinecone)."""

import pytest
from unittest.mock import MagicMock, patch

from cppa_pinecone_sync import services
from cppa_pinecone_sync.sync import (
    _build_documents_from_raw,
    _empty_sync_result,
    _extract_new_failed_ids,
    sync_to_pinecone,
)


# --- _empty_sync_result ---


def test_empty_sync_result_structure():
    """_empty_sync_result returns dict with expected keys and zero/empty values."""
    result = _empty_sync_result()
    assert result == {
        "upserted": 0,
        "updated": 0,
        "total": 0,
        "failed_count": 0,
        "failed_ids": [],
        "attempted_source_ids": [],
        "successful_source_ids": [],
        "errors": [],
        "update_errors": [],
    }


# --- _build_documents_from_raw ---


def test_build_documents_from_raw_empty_list():
    """_build_documents_from_raw returns empty list for empty input."""
    result = _build_documents_from_raw([])
    assert result == []


def test_build_documents_from_raw_includes_doc_id():
    """_build_documents_from_raw includes item when metadata has doc_id."""
    raw = [
        {
            "ids": "1",
            "content": "hello",
            "metadata": {"doc_id": "doc-1"},
        },
    ]
    result = _build_documents_from_raw(raw)
    assert len(result) == 1
    assert result[0].page_content == "hello"
    assert result[0].metadata.get("doc_id") == "doc-1"
    assert result[0].metadata.get("table_ids") == "1"


def test_build_documents_from_raw_includes_url():
    """_build_documents_from_raw includes item when metadata has url (no doc_id)."""
    raw = [
        {
            "ids": "2",
            "content": "world",
            "metadata": {"url": "https://example.com/page"},
        },
    ]
    result = _build_documents_from_raw(raw)
    assert len(result) == 1
    assert result[0].metadata.get("url") == "https://example.com/page"
    assert result[0].metadata.get("table_ids") == "2"


def test_build_documents_from_raw_skips_missing_doc_id_and_url():
    """_build_documents_from_raw skips items with neither doc_id nor url in metadata."""
    raw = [
        {
            "ids": "x",
            "content": "no id",
            "metadata": {},
        },
    ]
    result = _build_documents_from_raw(raw)
    assert len(result) == 0


def test_build_documents_from_raw_mixed():
    """_build_documents_from_raw keeps valid items and skips invalid."""
    raw = [
        {"ids": "1", "content": "a", "metadata": {"doc_id": "1"}},
        {"ids": "2", "content": "b", "metadata": {}},
        {"ids": "3", "content": "c", "metadata": {"url": "https://x.com"}},
    ]
    result = _build_documents_from_raw(raw)
    assert len(result) == 2
    assert result[0].page_content == "a"
    assert result[1].page_content == "c"


# --- _extract_new_failed_ids ---


def test_extract_new_failed_ids_empty_result():
    """_extract_new_failed_ids returns [] when no failed_documents."""
    result = _extract_new_failed_ids({})
    assert result == []
    result = _extract_new_failed_ids({"failed_documents": []})
    assert result == []


def test_extract_new_failed_ids_single_id():
    """_extract_new_failed_ids extracts single id from failed_documents."""
    result = _extract_new_failed_ids(
        {
            "failed_documents": [{"ids": "id1"}],
        }
    )
    assert result == ["id1"]


def test_extract_new_failed_ids_comma_separated():
    """_extract_new_failed_ids splits comma-separated ids and strips."""
    result = _extract_new_failed_ids(
        {
            "failed_documents": [{"ids": "a, b , c"}],
        }
    )
    assert result == ["a", "b", "c"]


def test_extract_new_failed_ids_multiple_docs():
    """_extract_new_failed_ids collects ids from all failed_documents."""
    result = _extract_new_failed_ids(
        {
            "failed_documents": [
                {"ids": "1"},
                {"ids": "2,3"},
            ],
        }
    )
    assert set(result) == {"1", "2", "3"}


def test_extract_new_failed_ids_skips_empty():
    """_extract_new_failed_ids skips empty or missing ids."""
    result = _extract_new_failed_ids(
        {
            "failed_documents": [
                {"ids": ""},
                {},
                {"ids": "  ,  "},
                {"ids": "only"},
            ],
        }
    )
    assert result == ["only"]


# --- sync_to_pinecone (with mocked ingestion) ---


@pytest.mark.django_db
def test_sync_to_pinecone_empty_preprocess_returns_early(app_type):
    """sync_to_pinecone returns empty result and does not update sync status when preprocess returns no docs."""

    def preprocess(_failed_ids, _final_sync_at):
        return [], False

    result = sync_to_pinecone(app_type, "ns", preprocess)
    assert result["upserted"] == 0
    assert result["total"] == 0
    assert result["failed_ids"] == []
    assert services.get_final_sync_at(app_type) is None


@pytest.mark.django_db
def test_sync_to_pinecone_all_invalid_docs_returns_early(app_type):
    """sync_to_pinecone returns empty result and does not update sync status when all raw docs lack doc_id/url."""

    def preprocess(_failed_ids, _final_sync_at):
        return [
            {"ids": "1", "content": "x", "metadata": {}},
        ], False

    result = sync_to_pinecone(app_type, "ns", preprocess)
    assert result["upserted"] == 0
    assert result["total"] == 0
    assert services.get_final_sync_at(app_type) is None


@pytest.mark.django_db
@patch("cppa_pinecone_sync.sync._get_ingestion")
def test_sync_to_pinecone_calls_ingestion_and_updates_db(mock_get_ingestion, app_type):
    """sync_to_pinecone calls ingestion.upsert_documents, clears fail list, records failures, updates status."""
    mock_ingestion = MagicMock()
    mock_ingestion.upsert_documents.return_value = {
        "upserted": 2,
        "total": 2,
        "errors": [],
        "failed_documents": [],
    }
    mock_get_ingestion.return_value = mock_ingestion

    def preprocess(_failed_ids, _final_sync_at):
        return [
            {"ids": "1", "content": "a", "metadata": {"doc_id": "1"}},
            {"ids": "2", "content": "b", "metadata": {"doc_id": "2"}},
        ], False

    result = sync_to_pinecone(app_type, "test_ns", preprocess)

    mock_ingestion.upsert_documents.assert_called_once()
    call_kw = mock_ingestion.upsert_documents.call_args[1]
    assert call_kw["namespace"] == "test_ns"
    assert call_kw["is_chunked"] is False
    assert len(call_kw["documents"]) == 2

    assert result["upserted"] == 2
    assert result["updated"] == 0
    assert result["total"] == 2
    assert result["failed_count"] == 0
    assert result["failed_ids"] == []
    assert result["update_errors"] == []
    assert services.get_final_sync_at(app_type) is not None


@pytest.mark.django_db
@patch("cppa_pinecone_sync.sync._get_ingestion")
def test_sync_to_pinecone_returns_metadata_update_result(mock_get_ingestion, app_type):
    """sync_to_pinecone returns metadata update results when metas_to_update is provided."""
    mock_ingestion = MagicMock()
    mock_ingestion.upsert_documents.return_value = {
        "upserted": 1,
        "total": 1,
        "errors": [],
        "failed_documents": [],
    }
    mock_ingestion.update_documents.return_value = {
        "updated": 1,
        "total": 1,
        "errors": [],
        "failed_documents": [],
    }
    mock_get_ingestion.return_value = mock_ingestion

    def preprocess(_failed_ids, _final_sync_at):
        return (
            [{"ids": "1", "content": "a", "metadata": {"doc_id": "1"}}],
            False,
            [{"ids": "1", "content": "a", "metadata": {"doc_id": "1", "title": "T"}}],
        )

    result = sync_to_pinecone(app_type, "test_ns", preprocess)

    mock_ingestion.upsert_documents.assert_called_once()
    mock_ingestion.update_documents.assert_called_once()
    assert result["upserted"] == 1
    assert result["updated"] == 1
    assert result["update_errors"] == []


@pytest.mark.django_db
@patch("cppa_pinecone_sync.sync._get_ingestion")
def test_sync_to_pinecone_records_failed_ids(mock_get_ingestion, app_type):
    """sync_to_pinecone records failed source IDs in PineconeFailList when upsert has failed_documents."""
    mock_ingestion = MagicMock()
    mock_ingestion.upsert_documents.return_value = {
        "upserted": 0,
        "total": 1,
        "errors": ["error"],
        "failed_documents": [
            {"ids": "fail1,fail2", "metadata": {}},
        ],
    }
    mock_get_ingestion.return_value = mock_ingestion

    def preprocess(_failed_ids, _final_sync_at):
        return [
            {"ids": "fail1,fail2", "content": "x", "metadata": {"doc_id": "d1"}},
        ], False

    result = sync_to_pinecone(app_type, "ns", preprocess)

    assert result["failed_count"] == 1
    assert set(result["failed_ids"]) == {"fail1", "fail2"}
    failed_in_db = services.get_failed_ids(app_type)
    assert set(failed_in_db) == {"fail1", "fail2"}


@pytest.mark.django_db
@patch("cppa_pinecone_sync.sync._get_ingestion")
def test_sync_to_pinecone_clears_previous_failed_ids(mock_get_ingestion, app_type):
    """sync_to_pinecone clears existing PineconeFailList entries for app_type before recording new ones."""
    services.record_failed_ids(app_type, ["old1"])
    mock_ingestion = MagicMock()
    mock_ingestion.upsert_documents.return_value = {
        "upserted": 1,
        "total": 1,
        "errors": [],
        "failed_documents": [],
    }
    mock_get_ingestion.return_value = mock_ingestion

    def preprocess(_failed_ids, _final_sync_at):
        return [
            {"ids": "new1", "content": "c", "metadata": {"doc_id": "d1"}},
        ], False

    sync_to_pinecone(app_type, "ns", preprocess)
    assert services.get_failed_ids(app_type) == []
