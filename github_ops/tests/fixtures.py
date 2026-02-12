"""
Fixtures for github_ops app.
No models; fixtures for client/token mocks if needed.
"""

import pytest


@pytest.fixture
def mock_github_token(monkeypatch):
    """Set a fake GITHUB_TOKEN so get_github_token doesn't fail in tests that need it."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_fake_for_tests")
