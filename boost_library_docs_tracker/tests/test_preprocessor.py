"""Tests for boost_library_docs_tracker.preprocessor."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from boost_library_docs_tracker import preprocessor, services
from boost_library_docs_tracker.models import BoostDocContent
from boost_library_tracker import services as boost_library_services

_PAGE = "x" * 200  # long enough for downstream chunk validation if needed


@pytest.mark.django_db
def test_get_library_name_uses_latest_relation(
    boost_library_version,
    make_boost_library,
    make_boost_version,
    boost_doc_content,
):
    """_get_library_name prefers the most recently created documentation link."""
    older_version = boost_library_version
    newer_library = make_boost_library(name="asio")
    newer_boost_version = make_boost_version("1.82.0")
    newer_version, _ = boost_library_services.get_or_create_boost_library_version(
        newer_library,
        newer_boost_version,
        cpp_version="C++14",
        description="Asio library",
        key="asio",
        documentation="https://www.boost.org/doc/libs/1_82_0/libs/asio/doc/html/",
    )

    older_rel, _ = services.link_content_to_library_version(
        library_version_id=older_version.pk,
        doc_content_id=boost_doc_content.pk,
    )
    newer_rel, _ = services.link_content_to_library_version(
        library_version_id=newer_version.pk,
        doc_content_id=boost_doc_content.pk,
    )

    now = timezone.now()
    type(older_rel).objects.filter(pk=older_rel.pk).update(
        created_at=now - timedelta(days=1)
    )
    type(newer_rel).objects.filter(pk=newer_rel.pk).update(created_at=now)

    boost_doc_content.refresh_from_db()

    assert preprocessor._get_library_name(boost_doc_content) == "asio"


@pytest.mark.django_db
def test_get_library_name_returns_empty_without_relation(boost_doc_content):
    """_get_library_name returns an empty string when no relation exists."""
    assert preprocessor._get_library_name(boost_doc_content) == ""


@pytest.mark.django_db
@patch(
    "boost_library_docs_tracker.preprocessor.workspace.load_page_by_url",
    return_value=_PAGE,
)
def test_preprocess_metas_when_upserted_and_scraped_after_final_sync(
    _mock_load,
    boost_doc_content,
):
    """Stale upserted rows (scraped_at > final_sync_at) appear in metas_to_update only."""
    now = timezone.now()
    BoostDocContent.objects.filter(pk=boost_doc_content.pk).update(
        is_upserted=True,
        scraped_at=now,
    )
    final_sync = now - timedelta(hours=1)
    docs, chunked, metas = preprocessor.preprocess_for_pinecone([], final_sync)
    assert docs == []
    assert chunked is False
    assert len(metas) == 1
    assert metas[0]["metadata"]["doc_id"] == boost_doc_content.content_hash
    assert metas[0]["metadata"]["source_ids"] == str(boost_doc_content.pk)


@pytest.mark.django_db
@patch(
    "boost_library_docs_tracker.preprocessor.workspace.load_page_by_url",
    return_value=_PAGE,
)
def test_preprocess_no_metas_when_final_sync_at_none(_mock_load, boost_doc_content):
    """With final_sync_at None, metas_to_update is empty (no stale-metadata scan)."""
    docs, chunked, metas = preprocessor.preprocess_for_pinecone([], None)
    assert chunked is False
    assert metas == []
    assert len(docs) == 1
    assert docs[0]["metadata"]["source_ids"] == str(boost_doc_content.pk)


@pytest.mark.django_db
@patch(
    "boost_library_docs_tracker.preprocessor.workspace.load_page_by_url",
    return_value=_PAGE,
)
def test_preprocess_metas_empty_when_scraped_before_final_sync(
    _mock_load,
    boost_doc_content,
):
    """Upserted row scraped before final_sync_at is not in metas_to_update."""
    now = timezone.now()
    BoostDocContent.objects.filter(pk=boost_doc_content.pk).update(
        is_upserted=True,
        scraped_at=now - timedelta(hours=2),
    )
    final_sync = now - timedelta(hours=1)
    docs, _, metas = preprocessor.preprocess_for_pinecone([], final_sync)
    assert docs == []
    assert metas == []


@pytest.mark.django_db
@patch(
    "boost_library_docs_tracker.preprocessor.workspace.load_page_by_url",
    return_value=_PAGE,
)
def test_preprocess_meta_excludes_failed_ids(_mock_load, boost_doc_content):
    """Rows in failed_ids are not selected for metadata-only update."""
    now = timezone.now()
    BoostDocContent.objects.filter(pk=boost_doc_content.pk).update(
        is_upserted=True,
        scraped_at=now,
    )
    final_sync = now - timedelta(hours=1)
    docs, _, metas = preprocessor.preprocess_for_pinecone(
        [str(boost_doc_content.pk)], final_sync
    )
    assert metas == []
    assert len(docs) == 1
    assert docs[0]["metadata"]["source_ids"] == str(boost_doc_content.pk)
