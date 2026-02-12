"""Tests for boost_library_tracker.services (at least 3 test cases per function)."""

import pytest
from datetime import date

from boost_library_tracker import services
from boost_library_tracker.models import (
    BoostDependency,
    BoostLibraryCategoryRelationship,
    BoostLibraryRepository,
    BoostLibraryRoleRelationship,
    DependencyChangeLog,
)


# --- get_or_create_boost_library_repo (3+ tests) ---


@pytest.mark.django_db
def test_get_or_create_boost_library_repo_creates_new(github_repository):
    """get_or_create_boost_library_repo creates BoostLibraryRepository and returns (repo, True)."""
    repo, created = services.get_or_create_boost_library_repo(github_repository)
    assert created is True
    assert repo.pk == github_repository.pk
    assert isinstance(repo, BoostLibraryRepository)
    assert repo.repo_name == github_repository.repo_name


@pytest.mark.django_db
def test_get_or_create_boost_library_repo_gets_existing(
    boost_library_repository, github_repository
):
    """get_or_create_boost_library_repo returns existing and (repo, False)."""
    repo, created = services.get_or_create_boost_library_repo(github_repository)
    assert created is False
    assert repo.pk == boost_library_repository.pk


@pytest.mark.django_db
def test_get_or_create_boost_library_repo_updates_updated_at(
    boost_library_repository,
    github_repository,
):
    """get_or_create_boost_library_repo updates updated_at when existing."""

    old_updated = boost_library_repository.updated_at
    repo, created = services.get_or_create_boost_library_repo(github_repository)
    assert created is False
    repo.refresh_from_db()
    assert repo.updated_at >= old_updated


# --- get_or_create_boost_library (3+ tests) ---


@pytest.mark.django_db
def test_get_or_create_boost_library_creates_new(boost_library_repository):
    """get_or_create_boost_library creates new library and returns (lib, True)."""
    lib, created = services.get_or_create_boost_library(
        boost_library_repository,
        "new-lib",
    )
    assert created is True
    assert lib.name == "new-lib"
    assert lib.repo_id == boost_library_repository.pk


@pytest.mark.django_db
def test_get_or_create_boost_library_gets_existing(
    boost_library, boost_library_repository
):
    """get_or_create_boost_library returns existing and (lib, False)."""
    lib, created = services.get_or_create_boost_library(
        boost_library_repository,
        boost_library.name,
    )
    assert created is False
    assert lib.pk == boost_library.pk


@pytest.mark.django_db
def test_get_or_create_boost_library_empty_name_raises(boost_library_repository):
    """get_or_create_boost_library raises ValueError for empty or whitespace name."""
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_boost_library(boost_library_repository, "")
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_boost_library(boost_library_repository, "   ")


@pytest.mark.django_db
def test_get_or_create_boost_library_strips_whitespace(boost_library_repository):
    """get_or_create_boost_library strips leading/trailing whitespace from name."""
    lib, created = services.get_or_create_boost_library(
        boost_library_repository,
        "  trimmed  ",
    )
    assert created is True
    assert lib.name == "trimmed"


# --- get_or_create_boost_file (3+ tests) ---


@pytest.mark.django_db
def test_get_or_create_boost_file_creates_new(boost_library, github_file):
    """get_or_create_boost_file creates new BoostFile and returns (obj, True)."""
    obj, created = services.get_or_create_boost_file(github_file, boost_library)
    assert created is True
    assert obj.github_file_id == github_file.pk
    assert obj.library_id == boost_library.pk


@pytest.mark.django_db
def test_get_or_create_boost_file_gets_existing(boost_library, github_file):
    """get_or_create_boost_file returns existing and (obj, False)."""
    services.get_or_create_boost_file(github_file, boost_library)
    obj2, created2 = services.get_or_create_boost_file(github_file, boost_library)
    assert created2 is False
    assert obj2.pk == github_file.pk


@pytest.mark.django_db
def test_get_or_create_boost_file_updates_library_when_different(
    boost_library_repository,
    github_file,
):
    """get_or_create_boost_file updates library when file exists with different library."""
    lib1, _ = services.get_or_create_boost_library(boost_library_repository, "lib-a")
    lib2, _ = services.get_or_create_boost_library(boost_library_repository, "lib-b")
    services.get_or_create_boost_file(github_file, lib1)
    obj, created = services.get_or_create_boost_file(github_file, lib2)
    assert created is False
    obj.refresh_from_db()
    assert obj.library_id == lib2.pk


# --- get_or_create_boost_version (3+ tests) ---


@pytest.mark.django_db
def test_get_or_create_boost_version_creates_new():
    """get_or_create_boost_version creates new version and returns (obj, True)."""
    obj, created = services.get_or_create_boost_version("2.0.0")
    assert created is True
    assert obj.version == "2.0.0"
    assert obj.id is not None


@pytest.mark.django_db
def test_get_or_create_boost_version_gets_existing(boost_version):
    """get_or_create_boost_version returns existing and (obj, False)."""
    obj, created = services.get_or_create_boost_version(boost_version.version)
    assert created is False
    assert obj.pk == boost_version.pk


@pytest.mark.django_db
def test_get_or_create_boost_version_empty_raises():
    """get_or_create_boost_version raises ValueError for empty or whitespace version."""
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_boost_version("")
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_boost_version("   ")


@pytest.mark.django_db
def test_get_or_create_boost_version_updates_version_created_at(boost_version):
    """get_or_create_boost_version updates version_created_at when existing."""
    from datetime import datetime, timezone

    dt = datetime(2024, 6, 1, tzinfo=timezone.utc)
    obj, created = services.get_or_create_boost_version(
        boost_version.version,
        version_created_at=dt,
    )
    assert created is False
    obj.refresh_from_db()
    assert obj.version_created_at == dt


# --- get_or_create_boost_library_version (3+ tests) ---


@pytest.mark.django_db
def test_get_or_create_boost_library_version_creates_new(
    boost_library,
    make_boost_version,
):
    """get_or_create_boost_library_version creates new and returns (obj, True)."""
    ver = make_boost_version("9.0.0")
    obj, created = services.get_or_create_boost_library_version(
        boost_library,
        ver,
        cpp_version="C++20",
        description="New lib version",
    )
    assert created is True
    assert obj.library_id == boost_library.pk
    assert obj.version_id == ver.pk
    assert obj.cpp_version == "C++20"
    assert obj.description == "New lib version"


@pytest.mark.django_db
def test_get_or_create_boost_library_version_gets_existing(
    boost_library_version,
    boost_library,
    boost_version,
):
    """get_or_create_boost_library_version returns existing and (obj, False)."""
    obj, created = services.get_or_create_boost_library_version(
        boost_library,
        boost_version,
        cpp_version="C++17",
        description="Updated",
    )
    assert created is False
    assert obj.pk == boost_library_version.pk
    obj.refresh_from_db()
    assert obj.cpp_version == "C++17"
    assert obj.description == "Updated"


@pytest.mark.django_db
def test_get_or_create_boost_library_version_defaults_empty(
    make_boost_library,
    make_boost_version,
):
    """get_or_create_boost_library_version with empty cpp_version and description."""
    lib = make_boost_library(name="minimal-lib")
    ver = make_boost_version("1.0.0")
    obj, created = services.get_or_create_boost_library_version(lib, ver)
    assert created is True
    assert obj.cpp_version == ""
    assert obj.description == ""


# --- add_boost_dependency (3+ tests) ---


@pytest.mark.django_db
def test_add_boost_dependency_creates_new(
    make_boost_library,
    boost_library_repository,
    boost_version,
):
    """add_boost_dependency creates new dependency and returns (dep, True)."""
    client = make_boost_library(repo=boost_library_repository, name="client")
    dep_lib = make_boost_library(repo=boost_library_repository, name="dep")
    dep, created = services.add_boost_dependency(client, boost_version, dep_lib)
    assert created is True
    assert dep.client_library_id == client.pk
    assert dep.version_id == boost_version.pk
    assert dep.dep_library_id == dep_lib.pk


@pytest.mark.django_db
def test_add_boost_dependency_get_existing(
    make_boost_library,
    boost_library_repository,
    boost_version,
):
    """add_boost_dependency returns existing and (dep, False)."""
    client = make_boost_library(repo=boost_library_repository, name="c2")
    dep_lib = make_boost_library(repo=boost_library_repository, name="d2")
    services.add_boost_dependency(client, boost_version, dep_lib)
    dep2, created2 = services.add_boost_dependency(client, boost_version, dep_lib)
    assert created2 is False
    assert (
        BoostDependency.objects.filter(
            client_library=client,
            version=boost_version,
            dep_library=dep_lib,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_add_boost_dependency_idempotent(
    make_boost_library,
    boost_library_repository,
    boost_version,
):
    """add_boost_dependency is idempotent (same args multiple times)."""
    client = make_boost_library(repo=boost_library_repository, name="c3")
    dep_lib = make_boost_library(repo=boost_library_repository, name="d3")
    services.add_boost_dependency(client, boost_version, dep_lib)
    services.add_boost_dependency(client, boost_version, dep_lib)
    assert BoostDependency.objects.count() == 1


# --- add_dependency_changelog (3+ tests) ---


@pytest.mark.django_db
def test_add_dependency_changelog_creates_new(
    make_boost_library,
    boost_library_repository,
):
    """add_dependency_changelog creates new log and returns (log, True)."""
    client = make_boost_library(repo=boost_library_repository, name="ch-client")
    dep = make_boost_library(repo=boost_library_repository, name="ch-dep")
    log, created = services.add_dependency_changelog(
        client,
        dep,
        is_add=True,
        created_at=date(2024, 5, 1),
    )
    assert created is True
    assert log.client_library_id == client.pk
    assert log.dep_library_id == dep.pk
    assert log.is_add is True
    assert log.created_at == date(2024, 5, 1)


@pytest.mark.django_db
def test_add_dependency_changelog_gets_existing_and_updates_is_add(
    make_boost_library,
    boost_library_repository,
):
    """add_dependency_changelog returns existing and updates is_add when different."""
    client = make_boost_library(repo=boost_library_repository, name="ch2-client")
    dep = make_boost_library(repo=boost_library_repository, name="ch2-dep")
    services.add_dependency_changelog(
        client,
        dep,
        is_add=True,
        created_at=date(2024, 5, 2),
    )
    log2, created2 = services.add_dependency_changelog(
        client,
        dep,
        is_add=False,
        created_at=date(2024, 5, 2),
    )
    assert created2 is False
    log2.refresh_from_db()
    assert log2.is_add is False


@pytest.mark.django_db
def test_add_dependency_changelog_same_args_idempotent(
    make_boost_library,
    boost_library_repository,
):
    """add_dependency_changelog same client, dep, created_at returns existing."""
    client = make_boost_library(repo=boost_library_repository, name="ch3-client")
    dep = make_boost_library(repo=boost_library_repository, name="ch3-dep")
    services.add_dependency_changelog(
        client,
        dep,
        is_add=True,
        created_at=date(2024, 5, 3),
    )
    log2, created2 = services.add_dependency_changelog(
        client,
        dep,
        is_add=True,
        created_at=date(2024, 5, 3),
    )
    assert created2 is False
    assert (
        DependencyChangeLog.objects.filter(
            client_library=client,
            dep_library=dep,
            created_at=date(2024, 5, 3),
        ).count()
        == 1
    )


# --- get_or_create_boost_library_category (3+ tests) ---


@pytest.mark.django_db
def test_get_or_create_boost_library_category_creates_new():
    """get_or_create_boost_library_category creates new category and returns (obj, True)."""
    cat, created = services.get_or_create_boost_library_category("Container")
    assert created is True
    assert cat.name == "Container"
    assert cat.id is not None


@pytest.mark.django_db
def test_get_or_create_boost_library_category_gets_existing(boost_library_category):
    """get_or_create_boost_library_category returns existing and (obj, False)."""
    cat, created = services.get_or_create_boost_library_category(
        boost_library_category.name
    )
    assert created is False
    assert cat.pk == boost_library_category.pk


@pytest.mark.django_db
def test_get_or_create_boost_library_category_empty_raises():
    """get_or_create_boost_library_category raises ValueError for empty name."""
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_boost_library_category("")
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_boost_library_category("   ")


@pytest.mark.django_db
def test_get_or_create_boost_library_category_strips_whitespace():
    """get_or_create_boost_library_category strips leading/trailing whitespace."""
    cat, created = services.get_or_create_boost_library_category("  Algo  ")
    assert created is True
    assert cat.name == "Algo"


# --- add_library_category (3+ tests) ---


@pytest.mark.django_db
def test_add_library_category_creates_new(boost_library, make_boost_library_category):
    """add_library_category creates new relation and returns (rel, True)."""
    cat = make_boost_library_category("NewCategory")
    rel, created = services.add_library_category(boost_library, cat)
    assert created is True
    assert rel.library_id == boost_library.pk
    assert rel.category_id == cat.pk


@pytest.mark.django_db
def test_add_library_category_gets_existing(boost_library, boost_library_category):
    """add_library_category returns existing relation and (rel, False)."""
    services.add_library_category(boost_library, boost_library_category)
    rel2, created2 = services.add_library_category(
        boost_library,
        boost_library_category,
    )
    assert created2 is False
    assert (
        BoostLibraryCategoryRelationship.objects.filter(
            library=boost_library,
            category=boost_library_category,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_add_library_category_idempotent(boost_library, boost_library_category):
    """add_library_category is idempotent."""
    services.add_library_category(boost_library, boost_library_category)
    services.add_library_category(boost_library, boost_library_category)
    assert BoostLibraryCategoryRelationship.objects.count() == 1


# --- add_library_version_role (3+ tests) ---


@pytest.mark.django_db
def test_add_library_version_role_creates_new(
    boost_library_version,
    github_account,
):
    """add_library_version_role creates new relation and returns (rel, True)."""
    rel, created = services.add_library_version_role(
        boost_library_version,
        github_account,
        is_maintainer=True,
        is_author=True,
    )
    assert created is True
    assert rel.library_version_id == boost_library_version.pk
    assert rel.account_id == github_account.pk
    assert rel.is_maintainer is True
    assert rel.is_author is True


@pytest.mark.django_db
def test_add_library_version_role_gets_existing_and_accumulates_flags(
    boost_library_version,
    github_account,
):
    """add_library_version_role returns existing and ORs is_maintainer/is_author."""
    services.add_library_version_role(
        boost_library_version,
        github_account,
        is_maintainer=True,
        is_author=False,
    )
    rel2, created2 = services.add_library_version_role(
        boost_library_version,
        github_account,
        is_maintainer=False,
        is_author=True,
    )
    assert created2 is False
    rel2.refresh_from_db()
    assert rel2.is_maintainer is True
    assert rel2.is_author is True


@pytest.mark.django_db
def test_add_library_version_role_idempotent(
    boost_library_version,
    github_account,
):
    """add_library_version_role same args returns existing."""
    services.add_library_version_role(
        boost_library_version,
        github_account,
        is_maintainer=True,
    )
    rel2, created2 = services.add_library_version_role(
        boost_library_version,
        github_account,
        is_maintainer=True,
    )
    assert created2 is False
    assert (
        BoostLibraryRoleRelationship.objects.filter(
            library_version=boost_library_version,
            account=github_account,
        ).count()
        == 1
    )
