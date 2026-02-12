"""
Fixtures for boost_usage_tracker app.

Depends on github_activity_tracker (GitHubRepository, GitHubFile),
boost_library_tracker (BoostFile), and cppa_user_tracker (GitHubAccount).
All writes to boost_usage_tracker models go through boost_usage_tracker.services.
"""

import uuid

import pytest
from model_bakery import baker

from boost_usage_tracker import services as boost_usage_services
from boost_library_tracker import services as boost_library_services


@pytest.fixture
def external_github_repository(db, github_account):
    """A GitHubRepository representing an external C++ repo (not the Boost library repo)."""
    return baker.make(
        "github_activity_tracker.GitHubRepository",
        owner_account=github_account,
        repo_name="external-repo-" + uuid.uuid4().hex[:8],
        stars=10,
        forks=0,
    )


@pytest.fixture
def ext_repo(db, external_github_repository):
    """BoostExternalRepository for the external repo. Uses service API."""
    repo, _ = boost_usage_services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version="1.84.0",
        is_boost_used=True,
    )
    return repo


@pytest.fixture
def external_github_file(db, external_github_repository):
    """GitHubFile in the external repo (the source file that contains #include <boost/...>)."""
    return baker.make(
        "github_activity_tracker.GitHubFile",
        repo=external_github_repository,
        filename="src/main.cpp",
    )


@pytest.fixture
def boost_file(db, github_file, boost_library):
    """BoostFile (Boost header) from boost_library_tracker. Uses that app's service."""
    bf, _ = boost_library_services.get_or_create_boost_file(github_file, boost_library)
    return bf


@pytest.fixture
def make_ext_repo():
    """Factory: create BoostExternalRepository via service; creates parent repo if needed."""

    def _make(
        github_repository=None,
        boost_version="",
        is_boost_embedded=False,
        is_boost_used=False,
    ):
        if github_repository is None:
            github_repository = baker.make(
                "github_activity_tracker.GitHubRepository",
                repo_name="ext-" + uuid.uuid4().hex[:8],
            )
        return boost_usage_services.get_or_create_boost_external_repo(
            github_repository,
            boost_version=boost_version,
            is_boost_embedded=is_boost_embedded,
            is_boost_used=is_boost_used,
        )[0]

    return _make
