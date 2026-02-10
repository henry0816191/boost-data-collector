"""
Fixtures for github_activity_tracker app.
Uses model_bakery; repository fixtures depend on cppa_user_tracker.github_account.
"""
import uuid
import pytest
from model_bakery import baker


@pytest.fixture
def language(db):
    """Single Language instance."""
    return baker.make("github_activity_tracker.Language", name="C++")


@pytest.fixture
def license_obj(db):
    """Single License instance (named to avoid shadowing builtin)."""
    return baker.make(
        "github_activity_tracker.License",
        name="BSL-1.0",
        spdx_id="BSL-1.0",
    )


@pytest.fixture
def github_repository(db, github_account):
    """GitHubRepository with owner_account from cppa_user_tracker."""
    return baker.make(
        "github_activity_tracker.GitHubRepository",
        owner_account=github_account,
        repo_name="test-repo",
        stars=0,
        forks=0,
    )


@pytest.fixture
def make_language():
    """Factory: create Language with optional kwargs."""

    def _make(**kwargs):
        return baker.make("github_activity_tracker.Language", **kwargs)

    return _make


@pytest.fixture
def make_github_repository():
    """Factory: create GitHubRepository; requires owner_account or uses baker default."""

    def _make(**kwargs):
        if "owner_account" not in kwargs:
            kwargs["owner_account"] = baker.make("cppa_user_tracker.GitHubAccount")
        if "repo_name" not in kwargs:
            kwargs["repo_name"] = "repo-" + uuid.uuid4().hex[:8]
        return baker.make("github_activity_tracker.GitHubRepository", **kwargs)

    return _make
