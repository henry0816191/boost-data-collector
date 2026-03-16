"""Tests for boost_library_docs_tracker models (at least 3 test cases per model)."""

import pytest
from django.db import IntegrityError

from boost_library_docs_tracker.models import BoostDocContent, BoostLibraryDocumentation
from boost_library_docs_tracker import services


# --- BoostDocContent (3+ tests) ---


@pytest.mark.django_db
def test_boost_doc_content_content_hash_unique(boost_doc_content):
    """BoostDocContent has a unique content_hash constraint."""
    assert boost_doc_content.content_hash is not None
    assert boost_doc_content.id is not None
    with pytest.raises(IntegrityError):
        from model_bakery import baker

        baker.make(
            "boost_library_docs_tracker.BoostDocContent",
            content_hash=boost_doc_content.content_hash,
        )


@pytest.mark.django_db
def test_boost_doc_content_has_timestamps(boost_doc_content):
    """BoostDocContent has created_at and scraped_at."""
    assert boost_doc_content.created_at is not None
    assert boost_doc_content.scraped_at is not None


@pytest.mark.django_db
def test_boost_doc_content_ordering():
    """BoostDocContent orders by url."""
    assert BoostDocContent._meta.ordering == ["url"]


@pytest.mark.django_db
def test_boost_doc_content_stores_content_hash(boost_doc_content):
    """BoostDocContent stores content_hash (no page_content column)."""
    assert len(boost_doc_content.content_hash) == 64
    assert not hasattr(boost_doc_content, "page_content")


@pytest.mark.django_db
def test_boost_doc_content_str(boost_doc_content):
    """BoostDocContent __str__ returns the url."""
    assert str(boost_doc_content) == boost_doc_content.url


@pytest.mark.django_db
def test_boost_doc_content_default_is_upserted(boost_doc_content):
    """BoostDocContent default is_upserted is False."""
    assert boost_doc_content.is_upserted is False


@pytest.mark.django_db
def test_boost_doc_content_has_version_fks(boost_doc_content):
    """BoostDocContent has first_version and last_version FK fields (nullable)."""
    field_names = [f.name for f in BoostDocContent._meta.get_fields()]
    assert "first_version" in field_names
    assert "last_version" in field_names
    assert boost_doc_content.first_version_id is None
    assert boost_doc_content.last_version_id is None


# --- BoostLibraryDocumentation (3+ tests) ---


@pytest.mark.django_db
def test_boost_library_documentation_no_is_upserted_field():
    """BoostLibraryDocumentation no longer has is_upserted (moved to BoostDocContent)."""
    field_names = [f.name for f in BoostLibraryDocumentation._meta.get_fields()]
    assert "is_upserted" not in field_names


@pytest.mark.django_db
def test_boost_library_documentation_no_page_count_or_updated_at():
    """BoostLibraryDocumentation no longer has page_count or updated_at."""
    field_names = [f.name for f in BoostLibraryDocumentation._meta.get_fields()]
    assert "page_count" not in field_names
    assert "updated_at" not in field_names


@pytest.mark.django_db
def test_boost_library_documentation_links_version_and_content(
    boost_library_documentation,
    boost_library_version,
    boost_doc_content,
):
    """BoostLibraryDocumentation is linked to BoostLibraryVersion and BoostDocContent."""
    assert (
        boost_library_documentation.boost_library_version_id == boost_library_version.pk
    )
    assert boost_library_documentation.boost_doc_content_id == boost_doc_content.pk


@pytest.mark.django_db
def test_boost_library_documentation_unique_constraint(
    boost_library_version,
    boost_doc_content,
):
    """BoostLibraryDocumentation has unique constraint on (library_version, doc_content)."""
    services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk
    )
    with pytest.raises(IntegrityError):
        from model_bakery import baker

        baker.make(
            "boost_library_docs_tracker.BoostLibraryDocumentation",
            boost_library_version=boost_library_version,
            boost_doc_content=boost_doc_content,
        )


@pytest.mark.django_db
def test_boost_library_documentation_has_created_at(boost_library_documentation):
    """BoostLibraryDocumentation has created_at timestamp."""
    assert boost_library_documentation.created_at is not None


@pytest.mark.django_db
def test_boost_library_documentation_has_no_status_field():
    """BoostLibraryDocumentation no longer has a 'status' field or Status choices."""
    assert not hasattr(BoostLibraryDocumentation, "Status")
    field_names = [f.name for f in BoostLibraryDocumentation._meta.get_fields()]
    assert "status" not in field_names


@pytest.mark.django_db
def test_boost_library_documentation_reverse_relation(
    boost_library_documentation,
    boost_library_version,
    boost_doc_content,
):
    """BoostLibraryDocumentation accessible via library_version.doc_relations and doc_content.library_relations."""
    assert boost_library_version.doc_relations.filter(
        pk=boost_library_documentation.pk
    ).exists()
    assert boost_doc_content.library_relations.filter(
        pk=boost_library_documentation.pk
    ).exists()
