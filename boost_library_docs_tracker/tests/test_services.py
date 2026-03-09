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
    assert obj.is_upserted is False


@pytest.mark.django_db
def test_get_or_create_doc_content_unchanged_when_same_hash():
    """get_or_create_doc_content returns 'unchanged' when hash already exists."""
    services.get_or_create_doc_content(
        url="https://example.com/page",
        content_hash="b" * 64,
    )
    obj2, change_type = services.get_or_create_doc_content(
        url="https://example.com/page",
        content_hash="b" * 64,
    )
    assert change_type == "unchanged"
    assert BoostDocContent.objects.filter(content_hash="b" * 64).count() == 1


@pytest.mark.django_db
def test_get_or_create_doc_content_content_changed_when_url_differs():
    """get_or_create_doc_content returns 'content_changed' when url differs for same hash."""
    services.get_or_create_doc_content(
        url="https://example.com/old-page",
        content_hash="c" * 64,
    )
    obj2, change_type = services.get_or_create_doc_content(
        url="https://example.com/new-page",
        content_hash="c" * 64,
    )
    assert change_type == "content_changed"
    obj2.refresh_from_db()
    assert obj2.url == "https://example.com/new-page"


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
    from datetime import datetime, timezone
    from unittest.mock import patch

    t1 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2024, 6, 1, 12, 0, 1, tzinfo=timezone.utc)
    with patch("boost_library_docs_tracker.services._now", side_effect=[t1, t2]):
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
    assert obj2.scraped_at > old_scraped_at


@pytest.mark.django_db
def test_get_or_create_doc_content_sets_version_fks_on_create():
    """get_or_create_doc_content sets first_version and last_version on create when version_id is given."""
    from model_bakery import baker

    bv = baker.make("boost_library_tracker.BoostVersion")
    obj, change_type = services.get_or_create_doc_content(
        url="https://example.com/versioned",
        content_hash="1" * 64,
        version_id=bv.pk,
    )
    assert change_type == "created"
    assert obj.first_version_id == bv.pk
    assert obj.last_version_id == bv.pk


@pytest.mark.django_db
def test_get_or_create_doc_content_updates_last_version_on_unchanged():
    """get_or_create_doc_content updates last_version on second call with different version."""
    from model_bakery import baker

    bv1 = baker.make("boost_library_tracker.BoostVersion")
    bv2 = baker.make("boost_library_tracker.BoostVersion")
    obj1, _ = services.get_or_create_doc_content(
        url="https://example.com/versioned2",
        content_hash="2" * 64,
        version_id=bv1.pk,
    )
    obj2, change_type = services.get_or_create_doc_content(
        url="https://example.com/versioned2",
        content_hash="2" * 64,
        version_id=bv2.pk,
    )
    assert change_type == "unchanged"
    obj2.refresh_from_db()
    assert obj2.first_version_id == bv1.pk
    assert obj2.last_version_id == bv2.pk


# --- set_doc_content_upserted ---


@pytest.mark.django_db
def test_set_doc_content_upserted_sets_true(boost_doc_content):
    """set_doc_content_upserted sets is_upserted=True and persists it."""
    result = services.set_doc_content_upserted(boost_doc_content, True)
    assert result.is_upserted is True
    boost_doc_content.refresh_from_db()
    assert boost_doc_content.is_upserted is True


@pytest.mark.django_db
def test_set_doc_content_upserted_sets_false(boost_doc_content):
    """set_doc_content_upserted sets is_upserted=False after it was True."""
    services.set_doc_content_upserted(boost_doc_content, True)
    result = services.set_doc_content_upserted(boost_doc_content, False)
    assert result.is_upserted is False
    boost_doc_content.refresh_from_db()
    assert boost_doc_content.is_upserted is False


@pytest.mark.django_db
def test_set_doc_content_upserted_returns_object(boost_doc_content):
    """set_doc_content_upserted returns the same BoostDocContent instance."""
    result = services.set_doc_content_upserted(boost_doc_content, True)
    assert result.pk == boost_doc_content.pk


# --- set_doc_content_upserted_by_ids ---


@pytest.mark.django_db
def test_set_doc_content_upserted_by_ids_bulk_update(boost_doc_content):
    """set_doc_content_upserted_by_ids marks multiple rows at once."""
    count = services.set_doc_content_upserted_by_ids([boost_doc_content.pk], True)
    assert count == 1
    boost_doc_content.refresh_from_db()
    assert boost_doc_content.is_upserted is True


@pytest.mark.django_db
def test_set_doc_content_upserted_by_ids_empty_list():
    """set_doc_content_upserted_by_ids returns 0 for an empty list without hitting the DB."""
    count = services.set_doc_content_upserted_by_ids([], True)
    assert count == 0


@pytest.mark.django_db
def test_set_doc_content_upserted_by_ids_unknown_ids():
    """set_doc_content_upserted_by_ids with non-existent PKs returns 0."""
    count = services.set_doc_content_upserted_by_ids([999999], True)
    assert count == 0


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
    )
    assert created is True
    assert rel.boost_library_version_id == boost_library_version.pk
    assert rel.boost_doc_content_id == boost_doc_content.pk


@pytest.mark.django_db
def test_link_content_to_library_version_gets_existing(
    boost_library_version,
    boost_doc_content,
):
    """link_content_to_library_version returns existing and (rel, False)."""
    services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk
    )
    rel2, created = services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk
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
def test_link_content_to_library_version_idempotent(
    boost_library_version,
    boost_doc_content,
):
    """Calling link_content_to_library_version twice does not create duplicates."""
    rel1, created1 = services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk
    )
    rel2, created2 = services.link_content_to_library_version(
        boost_library_version.pk, boost_doc_content.pk
    )
    assert created1 is True
    assert created2 is False
    assert rel1.pk == rel2.pk


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


# --- get_unupserted_doc_contents ---


@pytest.mark.django_db
def test_get_unupserted_doc_contents_returns_unupserted(boost_doc_content):
    """get_unupserted_doc_contents returns rows where is_upserted=False."""
    qs = services.get_unupserted_doc_contents()
    assert qs.filter(pk=boost_doc_content.pk).exists()


@pytest.mark.django_db
def test_get_unupserted_doc_contents_excludes_upserted(boost_doc_content):
    """get_unupserted_doc_contents excludes rows where is_upserted=True."""
    services.set_doc_content_upserted(boost_doc_content, True)
    qs = services.get_unupserted_doc_contents()
    assert not qs.filter(pk=boost_doc_content.pk).exists()
