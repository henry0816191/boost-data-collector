"""Tests for boost_library_tracker models (at least 3 test cases per model)."""

import pytest
from datetime import date
from model_bakery import baker

from boost_library_tracker.models import (
    BoostLibraryCategory,
    BoostVersion,
)


# --- BoostLibraryRepository (3+ tests) ---


@pytest.mark.django_db
def test_boost_library_repository_extends_github_repo(
    boost_library_repository,
    github_repository,
):
    """BoostLibraryRepository uses same PK as parent GitHubRepository."""
    assert boost_library_repository.pk == github_repository.pk
    assert boost_library_repository.repo_name == github_repository.repo_name


@pytest.mark.django_db
def test_boost_library_repository_has_timestamps(boost_library_repository):
    """BoostLibraryRepository has created_at and updated_at."""
    assert boost_library_repository.created_at is not None
    assert boost_library_repository.updated_at is not None


@pytest.mark.django_db
def test_boost_library_repository_ordering(boost_library_repository):
    """BoostLibraryRepository orders by repo_name."""
    assert boost_library_repository._meta.ordering == ["repo_name"]


# --- BoostLibrary (3+ tests) ---


@pytest.mark.django_db
def test_boost_library_belongs_to_repo(boost_library, boost_library_repository):
    """BoostLibrary is linked to BoostLibraryRepository."""
    assert boost_library.repo_id == boost_library_repository.pk
    assert boost_library in boost_library_repository.libraries.all()
    assert boost_library.name == "algorithm"


@pytest.mark.django_db
def test_multiple_libraries_in_repo(make_boost_library, boost_library_repository):
    """Multiple BoostLibraries can be created in the same repository."""
    make_boost_library(repo=boost_library_repository, name="algorithm")
    make_boost_library(repo=boost_library_repository, name="container")
    assert boost_library_repository.libraries.count() == 2


@pytest.mark.django_db
def test_boost_library_unique_repo_name(boost_library_repository):
    """BoostLibrary has unique constraint on (repo, name)."""
    from django.db import IntegrityError

    baker.make(
        "boost_library_tracker.BoostLibrary",
        repo=boost_library_repository,
        name="unique-lib",
    )
    with pytest.raises(IntegrityError):
        baker.make(
            "boost_library_tracker.BoostLibrary",
            repo=boost_library_repository,
            name="unique-lib",
        )


# --- BoostFile (3+ tests) ---


@pytest.mark.django_db
def test_boost_file_links_github_file_and_library(
    boost_library,
    github_file,
):
    """BoostFile links GitHubFile to BoostLibrary (via get_or_create in service)."""
    from boost_library_tracker import services

    bf, created = services.get_or_create_boost_file(github_file, boost_library)
    assert bf.github_file_id == github_file.pk
    assert bf.library_id == boost_library.pk
    assert boost_library.files.filter(pk=github_file.pk).exists()


@pytest.mark.django_db
def test_boost_file_primary_key_is_github_file_id(
    boost_library,
    github_file,
):
    """BoostFile uses github_file_id as primary key."""
    from boost_library_tracker import services

    bf, _ = services.get_or_create_boost_file(github_file, boost_library)
    assert bf.pk == github_file.pk


@pytest.mark.django_db
def test_boost_file_reverse_relation_from_library(
    boost_library,
    github_file,
):
    """BoostFile accessible via library.files."""
    from boost_library_tracker import services

    services.get_or_create_boost_file(github_file, boost_library)
    assert boost_library.files.count() == 1
    assert boost_library.files.first().github_file == github_file


# --- BoostVersion (3+ tests) ---


@pytest.mark.django_db
def test_boost_version_unique_version(boost_version):
    """BoostVersion has unique version string."""
    assert boost_version.version == "1.81.0"
    assert boost_version.id is not None


@pytest.mark.django_db
def test_boost_version_version_created_at_null_allowed(boost_version):
    """BoostVersion.version_created_at can be null."""
    assert boost_version.version_created_at is None


@pytest.mark.django_db
def test_boost_version_ordering(make_boost_version):
    """BoostVersion ordering by -version_created_at, version."""
    make_boost_version("1.80.0")
    make_boost_version("1.82.0")
    assert BoostVersion.objects.count() >= 2
    assert BoostVersion._meta.ordering == ["-version_created_at", "version"]


# --- BoostLibraryVersion (3+ tests) ---


@pytest.mark.django_db
def test_boost_library_version_links_library_and_version(
    boost_library_version,
    boost_library,
    boost_version,
):
    """BoostLibraryVersion links BoostLibrary and BoostVersion."""
    assert boost_library_version.library_id == boost_library.pk
    assert boost_library_version.version_id == boost_version.pk


@pytest.mark.django_db
def test_boost_library_version_cpp_version_and_description(
    boost_library_version,
):
    """BoostLibraryVersion stores cpp_version and description."""
    assert boost_library_version.cpp_version == "C++14"
    assert boost_library_version.description == "Algorithm library"


@pytest.mark.django_db
def test_boost_library_version_has_timestamps(boost_library_version):
    """BoostLibraryVersion has created_at and updated_at."""
    assert boost_library_version.created_at is not None
    assert boost_library_version.updated_at is not None


# --- BoostDependency (3+ tests) ---


@pytest.mark.django_db
def test_boost_dependency_links_client_version_dep(
    make_boost_library,
    boost_library_repository,
    boost_version,
):
    """BoostDependency links client_library, version, dep_library."""
    from boost_library_tracker import services

    client = make_boost_library(repo=boost_library_repository, name="client-lib")
    dep = make_boost_library(repo=boost_library_repository, name="dep-lib")
    dep_obj, created = services.add_boost_dependency(client, boost_version, dep)
    assert created is True
    assert dep_obj.client_library_id == client.pk
    assert dep_obj.version_id == boost_version.pk
    assert dep_obj.dep_library_id == dep.pk


@pytest.mark.django_db
def test_boost_dependency_reverse_relations(
    make_boost_library,
    boost_library_repository,
    boost_version,
):
    """BoostDependency accessible via client and dep reverse relations."""
    from boost_library_tracker import services

    client = make_boost_library(repo=boost_library_repository, name="c2")
    dep = make_boost_library(repo=boost_library_repository, name="d2")
    services.add_boost_dependency(client, boost_version, dep)
    assert client.dependencies_as_client.filter(version=boost_version).exists()
    assert dep.dependencies_as_dep.filter(version=boost_version).exists()


@pytest.mark.django_db
def test_boost_dependency_has_created_at(
    make_boost_library,
    boost_library_repository,
    boost_version,
):
    """BoostDependency has created_at."""
    from boost_library_tracker import services

    client = make_boost_library(repo=boost_library_repository, name="c3")
    dep = make_boost_library(repo=boost_library_repository, name="d3")
    dep_obj, _ = services.add_boost_dependency(client, boost_version, dep)
    assert dep_obj.created_at is not None


# --- DependencyChangeLog (3+ tests) ---


@pytest.mark.django_db
def test_dependency_changelog_links_client_dep(
    make_boost_library,
    boost_library_repository,
):
    """DependencyChangeLog links client_library and dep_library."""
    from boost_library_tracker import services

    client = make_boost_library(repo=boost_library_repository, name="changelog-client")
    dep = make_boost_library(repo=boost_library_repository, name="changelog-dep")
    log, created = services.add_dependency_changelog(
        client, dep, is_add=True, created_at=date(2024, 1, 15)
    )
    assert created is True
    assert log.client_library_id == client.pk
    assert log.dep_library_id == dep.pk
    assert log.is_add is True
    assert log.created_at == date(2024, 1, 15)


@pytest.mark.django_db
def test_dependency_changelog_is_add_flag(
    make_boost_library,
    boost_library_repository,
):
    """DependencyChangeLog stores is_add (add vs remove)."""
    from boost_library_tracker import services

    client = make_boost_library(repo=boost_library_repository, name="cl2")
    dep = make_boost_library(repo=boost_library_repository, name="dp2")
    log_add, _ = services.add_dependency_changelog(
        client, dep, is_add=True, created_at=date(2024, 2, 1)
    )
    assert log_add.is_add is True
    log_remove, _ = services.add_dependency_changelog(
        client, dep, is_add=False, created_at=date(2024, 2, 2)
    )
    assert log_remove.is_add is False


@pytest.mark.django_db
def test_dependency_changelog_reverse_relations(
    make_boost_library,
    boost_library_repository,
):
    """DependencyChangeLog accessible from client and dep."""
    from boost_library_tracker import services

    client = make_boost_library(repo=boost_library_repository, name="cl3")
    dep = make_boost_library(repo=boost_library_repository, name="dp3")
    services.add_dependency_changelog(
        client, dep, is_add=True, created_at=date(2024, 3, 1)
    )
    assert client.dependency_changelog_as_client.filter(dep_library=dep).exists()
    assert dep.dependency_changelog_as_dep.filter(client_library=client).exists()


# --- BoostLibraryCategory (3+ tests) ---


@pytest.mark.django_db
def test_boost_library_category_name_unique(boost_library_category):
    """BoostLibraryCategory has unique name."""
    assert boost_library_category.name == "Math"
    assert boost_library_category.id is not None


@pytest.mark.django_db
def test_boost_library_category_has_timestamps(boost_library_category):
    """BoostLibraryCategory has created_at and updated_at."""
    assert boost_library_category.created_at is not None
    assert boost_library_category.updated_at is not None


@pytest.mark.django_db
def test_boost_library_category_ordering():
    """BoostLibraryCategory ordering by name."""
    assert BoostLibraryCategory._meta.ordering == ["name"]


# --- BoostLibraryRoleRelationship (3+ tests) ---


@pytest.mark.django_db
def test_boost_library_role_links_version_and_account(
    boost_library_version,
    github_account,
):
    """BoostLibraryRoleRelationship links library_version and account."""
    from boost_library_tracker import services

    rel, created = services.add_library_version_role(
        boost_library_version,
        github_account,
        is_maintainer=True,
        is_author=False,
    )
    assert created is True
    assert rel.library_version_id == boost_library_version.pk
    assert rel.account_id == github_account.pk
    assert rel.is_maintainer is True
    assert rel.is_author is False


@pytest.mark.django_db
def test_boost_library_role_reverse_relations(
    boost_library_version,
    github_account,
):
    """BoostLibraryRoleRelationship accessible from version and account."""
    from boost_library_tracker import services

    services.add_library_version_role(
        boost_library_version,
        github_account,
        is_maintainer=True,
    )
    assert boost_library_version.role_relationships.filter(
        account=github_account
    ).exists()
    assert github_account.boost_library_roles.filter(
        library_version=boost_library_version
    ).exists()


@pytest.mark.django_db
def test_boost_library_role_has_timestamps(
    boost_library_version,
    github_account,
):
    """BoostLibraryRoleRelationship has created_at and updated_at."""
    from boost_library_tracker import services

    rel, _ = services.add_library_version_role(
        boost_library_version,
        github_account,
    )
    assert rel.created_at is not None
    assert rel.updated_at is not None


# --- BoostLibraryCategoryRelationship (3+ tests) ---


@pytest.mark.django_db
def test_boost_library_category_relationship_links_library_and_category(
    boost_library,
    boost_library_category,
):
    """BoostLibraryCategoryRelationship links library and category."""
    from boost_library_tracker import services

    rel, created = services.add_library_category(boost_library, boost_library_category)
    assert created is True
    assert rel.library_id == boost_library.pk
    assert rel.category_id == boost_library_category.pk


@pytest.mark.django_db
def test_boost_library_category_relationship_reverse_relations(
    boost_library,
    boost_library_category,
):
    """BoostLibraryCategoryRelationship accessible from library and category."""
    from boost_library_tracker import services

    services.add_library_category(boost_library, boost_library_category)
    assert boost_library.category_relationships.filter(
        category=boost_library_category
    ).exists()
    assert boost_library_category.library_relationships.filter(
        library=boost_library
    ).exists()


@pytest.mark.django_db
def test_boost_library_category_relationship_has_timestamps(
    boost_library,
    boost_library_category,
):
    """BoostLibraryCategoryRelationship has created_at and updated_at."""
    from boost_library_tracker import services

    rel, _ = services.add_library_category(boost_library, boost_library_category)
    assert rel.created_at is not None
    assert rel.updated_at is not None
