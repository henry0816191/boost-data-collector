"""
Fixtures for cppa_user_tracker app.
Uses model_bakery (baker) for Identity, GitHubAccount, etc.
"""

import pytest
from model_bakery import baker

from cppa_user_tracker.models import GitHubAccountType


@pytest.fixture
def identity(db):
    """Single Identity instance."""
    return baker.make("cppa_user_tracker.Identity", display_name="Test Identity")


@pytest.fixture
def github_account(db, identity):
    """GitHubAccount linked to an Identity."""
    return baker.make(
        "cppa_user_tracker.GitHubAccount",
        identity=identity,
        github_account_id=12345,
        username="testuser",
        display_name="Test User",
        account_type=GitHubAccountType.USER,
    )


@pytest.fixture
def make_identity():
    """Factory: create Identity with optional kwargs."""

    def _make(**kwargs):
        return baker.make("cppa_user_tracker.Identity", **kwargs)

    return _make


@pytest.fixture
def make_github_account():
    """Factory: create GitHubAccount with optional kwargs (identity created if not provided)."""

    def _make(**kwargs):
        if "identity" not in kwargs:
            kwargs["identity"] = baker.make("cppa_user_tracker.Identity")
        if "github_account_id" not in kwargs:
            kwargs["github_account_id"] = 99999
        return baker.make("cppa_user_tracker.GitHubAccount", **kwargs)

    return _make


@pytest.fixture
def tmp_identity(db):
    """Single TmpIdentity instance (staging)."""
    return baker.make("cppa_user_tracker.TmpIdentity", display_name="Tmp Identity")


@pytest.fixture
def make_tmp_identity():
    """Factory: create TmpIdentity with optional kwargs."""

    def _make(**kwargs):
        return baker.make("cppa_user_tracker.TmpIdentity", **kwargs)

    return _make
