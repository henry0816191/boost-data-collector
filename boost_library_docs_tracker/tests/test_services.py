"""Tests for boost_library_docs_tracker.services (at least 3 test cases per function)."""

import pytest

from boost_library_docs_tracker import services
from boost_library_docs_tracker.models import BoostDocContent, BoostLibraryDocumentation


# --- get_or_create_doc_content ---


@pytest.mark.django_db
def test_get_or_create_doc_content_creates_new():
    """get_or_create_doc_content creates a new row and returns (obj, 'created')."""
    obj, change_type = services.get_or_create_doc_content(
        url="https://example.com/page",
        content_hash="a" * 64,
    )
    assert change_type == "created"
    assert obj.pk is not None
    assert obj.url == "https://example.com/page"
    assert obj.content_hash == "a" * 64
    assert obj.scraped_at is not None
    assert obj.created_at is not None


@pytest.mark.django_db
def test_get_or_create_doc_content_unchanged_when_same_hash():
    """get_or_create_doc_content returns 'unchanged' when hash matches."""
    services.get_or_create_doc_content(
        url="https://example.com/page",
        content_hash="b" * 64,
    )
    obj2, change_type = services.get_or_create_doc_content(
        url="https://example.com/page",
        content_hash="b" * 64,
    )
    assert change_type == "unchanged"
    assert BoostDocContent.objects.filter(url="https://example.com/page").count() == 1


@pytest.mark.django_db
def test_get_or_create_doc_content_content_changed_when_hash_differs():
    """get_or_create_doc_content returns 'content_changed' when hash differs."""
    services.get_or_create_doc_content(
        url="https://example.com/page",
        content_hash="c" * 64,
    )
    obj2, change_type = services.get_or_create_doc_content(
        url="https://example.com/page",
        content_hash="d" * 64,
    )
    assert change_type == "content_changed"
    obj2.refresh_from_db()
    assert obj2.content_hash == "d" * 64


@pytest.mark.django_db
def test_get_or_create_doc_content_empty_url_raises():
    """get_or_create_doc_content raises ValueError for empty or whitespace url."""
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_doc_content("", "e" * 64)
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_doc_content("   ", "e" * 64)


@pytest.mark.django_db
def test_get_or_create_doc_content_updates_scraped_at_on_unchanged():
    """get_or_create_doc_content updates scraped_at even when content is unchanged."""
    obj1, _ = services.get_or_create_doc_content(
        url="https://example.com/page2",
        content_hash="f" * 64,
    )
    old_scraped_at = obj1.scraped_at
    obj2, change_type = services.get_or_create_doc_content(
        url="https://example.com/page2",
        content_hash="f" * 64,
    )
    assert change_type == "unchanged"
    obj2.refresh_from_db()
    assert obj2.scraped_at >= old_scraped_at


# --- link_content_to_library_version ---


@pytest.mark.django_db
def test_link_content_to_library_version_creates_new(
    boost_library_version,
    boost_doc_content,
):
    """link_content_to_library_version creates a new relation and returns (rel, True)."""
    rel, created = services.link_content_to_library_version(
        library_version_id=boost_library_version.pk,
        doc_content_id=boost_doc_content.pk,
        page_count=10,
    )
    assert created is True
    assert rel.boost_library_version_id == boost_library_version.pk
    assert rel.boost_doc_content_id == boost_doc_content.pk
    assert rel.page_count == 10


@pytest.mark.django_db
def test_link_content_to_library_version_gets_existing(
    boost_library_version,
    boost_doc_content,
):
    """link_content_to_library_version returns existing and (rel, False)."""
    services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk, 5
    )
    rel2, created = services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk, 5
    )
    assert created is False
    assert (
        BoostLibraryDocumentation.objects.filter(
            boost_library_version=boost_library_version,
            boost_doc_content=boost_doc_content,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_link_content_to_library_version_updates_page_count(
    boost_library_version,
    boost_doc_content,
):
    """link_content_to_library_version updates page_count when it changes."""
    services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk, 3
    )
    rel, created = services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk, 7
    )
    assert created is False
    rel.refresh_from_db()
    assert rel.page_count == 7


# --- set_is_upserted ---


@pytest.mark.django_db
def test_set_is_upserted_sets_true(boost_library_documentation):
    """set_is_upserted sets is_upserted=True and persists it."""
    result = services.set_is_upserted(boost_library_documentation, True)
    assert result.is_upserted is True
    boost_library_documentation.refresh_from_db()
    assert boost_library_documentation.is_upserted is True


@pytest.mark.django_db
def test_set_is_upserted_sets_false(boost_library_documentation):
    """set_is_upserted sets is_upserted=False after it was True."""
    services.set_is_upserted(boost_library_documentation, True)
    result = services.set_is_upserted(boost_library_documentation, False)
    assert result.is_upserted is False
    boost_library_documentation.refresh_from_db()
    assert boost_library_documentation.is_upserted is False


@pytest.mark.django_db
def test_set_is_upserted_updates_updated_at(boost_library_documentation):
    """set_is_upserted touches updated_at."""
    old_updated = boost_library_documentation.updated_at
    services.set_is_upserted(boost_library_documentation, True)
    boost_library_documentation.refresh_from_db()
    assert boost_library_documentation.updated_at >= old_updated


# --- set_is_upserted_by_ids ---


@pytest.mark.django_db
def test_set_is_upserted_by_ids_bulk_update(boost_library_documentation):
    """set_is_upserted_by_ids marks multiple rows at once."""
    count = services.set_is_upserted_by_ids([boost_library_documentation.pk], True)
    assert count == 1
    boost_library_documentation.refresh_from_db()
    assert boost_library_documentation.is_upserted is True


@pytest.mark.django_db
def test_set_is_upserted_by_ids_empty_list():
    """set_is_upserted_by_ids returns 0 for an empty list without hitting the DB."""
    count = services.set_is_upserted_by_ids([], True)
    assert count == 0


@pytest.mark.django_db
def test_set_is_upserted_by_ids_unknown_ids():
    """set_is_upserted_by_ids with non-existent PKs returns 0."""
    count = services.set_is_upserted_by_ids([999999], True)
    assert count == 0


# --- get_docs_for_library_version ---


@pytest.mark.django_db
def test_get_docs_for_library_version_returns_relations(
    boost_library_documentation,
    boost_library_version,
):
    """get_docs_for_library_version returns all docs for the given library version."""
    qs = services.get_docs_for_library_version(boost_library_version.pk)
    assert qs.filter(pk=boost_library_documentation.pk).exists()


@pytest.mark.django_db
def test_get_docs_for_library_version_empty_when_no_docs(boost_library_version):
    """get_docs_for_library_version returns empty queryset when no docs exist."""
    qs = services.get_docs_for_library_version(boost_library_version.pk)
    assert qs.count() == 0


@pytest.mark.django_db
def test_get_docs_for_library_version_does_not_return_other_versions(
    boost_library_documentation,
    make_boost_library_documentation,
    boost_library_version,
):
    """get_docs_for_library_version does not leak docs from other library versions."""
    from model_bakery import baker
    other_lv = baker.make("boost_library_tracker.BoostLibraryVersion")
    make_boost_library_documentation(library_version=other_lv)

    qs = services.get_docs_for_library_version(boost_library_version.pk)
    pks = set(qs.values_list("pk", flat=True))
    assert boost_library_documentation.pk in pks
    other_qs = services.get_docs_for_library_version(other_lv.pk)
    assert not pks.intersection(set(other_qs.values_list("pk", flat=True)))
