"""
Fixtures for cppa_pinecone_sync app.

No app-specific fixtures required for basic model/service tests;
models are created via services or baker in tests.
"""

import pytest


@pytest.fixture
def app_type():
    """Default app_type for sync_to_pinecone tests (CharField in DB)."""
    return "slack"


@pytest.fixture
def failed_id_list():
    """Sample list of failed IDs for record_failed_ids tests."""
    return ["id1", "id2", "id3"]
