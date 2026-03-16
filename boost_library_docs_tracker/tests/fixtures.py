"""
Fixtures for boost_library_docs_tracker app.
Depends on boost_library_tracker fixtures (boost_library_version).
All model creation goes through the service API (see boost_library_docs_tracker.services).
"""

import pytest

from boost_library_docs_tracker import services


@pytest.fixture
def boost_doc_content(db):
    """Single BoostDocContent row. Uses service API."""
    obj, _ = services.get_or_create_doc_content(
        url="https://www.boost.org/doc/libs/1_81_0/libs/algorithm/doc/",
        content_hash="abc123" + "0" * 58,
    )
    return obj


@pytest.fixture
def make_boost_doc_content(db):
    """Factory: create BoostDocContent via service API."""

    def _make(url=None, content_hash=None):
        import uuid

        url = (
            url or f"https://www.boost.org/doc/libs/1_81_0/libs/{uuid.uuid4().hex[:8]}/"
        )
        content_hash = content_hash or (uuid.uuid4().hex * 2)[:64]
        obj, _ = services.get_or_create_doc_content(url, content_hash)
        return obj

    return _make


@pytest.fixture
def boost_library_documentation(db, boost_library_version, boost_doc_content):
    """Single BoostLibraryDocumentation row. Uses service API."""
    rel, _ = services.link_content_to_library_version(
        library_version_id=boost_library_version.pk,
        doc_content_id=boost_doc_content.pk,
    )
    return rel


@pytest.fixture
def make_boost_library_documentation(db, boost_library_version, make_boost_doc_content):
    """Factory: create BoostLibraryDocumentation via service API."""

    def _make(library_version=None, doc_content=None):
        lv = library_version or boost_library_version
        dc = doc_content or make_boost_doc_content()
        rel, _ = services.link_content_to_library_version(
            library_version_id=lv.pk,
            doc_content_id=dc.pk,
        )
        return rel

    return _make
