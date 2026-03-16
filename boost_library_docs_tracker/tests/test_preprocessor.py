"""Tests for boost_library_docs_tracker.preprocessor."""

from datetime import timedelta

import pytest
from django.utils import timezone

from boost_library_docs_tracker import preprocessor, services
from boost_library_tracker import services as boost_library_services


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
