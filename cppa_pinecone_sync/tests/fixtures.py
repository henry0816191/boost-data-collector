"""
Fixtures for cppa_pinecone_sync app.

No app-specific fixtures required for basic model/service tests;
models are created via services or baker in tests.
"""

import pytest


@pytest.fixture
def app_id():
    """Default app_id for sync_to_pinecone tests (stored as str(app_id) in DB)."""
    return 1


@pytest.fixture
def failed_id_list():
    """Sample list of failed IDs for record_failed_ids tests."""
    return ["id1", "id2", "id3"]
