"""Tests for github_activity_tracker models."""

import pytest
from django.db import IntegrityError

from github_activity_tracker.models import (
    CreatedReposByLanguage,
    GitHubRepository,
)


@pytest.mark.django_db
def test_language_creation(language):
    """Language can be created with name."""
    assert language.name == "C++"
    assert language.id is not None


@pytest.mark.django_db
def test_language_has_created_at(language):
    """Language has auto_now_add created_at."""
    assert language.created_at is not None


@pytest.mark.django_db
def test_language_unique_name(make_language):
    """Language name is unique; duplicate raises IntegrityError."""
    make_language(name="Python")
    with pytest.raises(IntegrityError):
        make_language(name="Python")


@pytest.mark.django_db
def test_github_repository_owner_relation(github_repository, github_account):
    """GitHubRepository is linked to owner GitHubAccount."""
    assert github_repository.owner_account_id == github_account.id
    assert github_repository in github_account.repositories.all()


@pytest.mark.django_db
def test_github_repository_unique_owner_repo(
    github_repository, github_account, make_github_repository
):
    """GitHubRepository has unique (owner_account, repo_name); duplicate raises IntegrityError."""
    with pytest.raises(IntegrityError):
        GitHubRepository.objects.create(
            owner_account=github_account,
            repo_name=github_repository.repo_name,
        )


@pytest.mark.django_db
def test_license_creation(license_obj):
    """License can be created with name, spdx_id."""
    assert license_obj.name == "BSL-1.0"
    assert license_obj.spdx_id == "BSL-1.0"
    assert license_obj.id is not None


@pytest.mark.django_db
def test_created_repos_by_language_unique_language_year(language):
    """CreatedReposByLanguage enforces unique (language, year)."""
    CreatedReposByLanguage.objects.create(
        language=language,
        year=2025,
        all_repos=100,
        significant_repos=10,
    )
    with pytest.raises(IntegrityError):
        CreatedReposByLanguage.objects.create(
            language=language,
            year=2025,
            all_repos=120,
            significant_repos=12,
        )
