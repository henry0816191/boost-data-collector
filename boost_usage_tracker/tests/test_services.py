"""Tests for boost_usage_tracker.services."""

from datetime import datetime, timezone

import pytest

from boost_usage_tracker import services
from boost_usage_tracker.models import (
    BoostExternalRepository,
    BoostMissingHeaderTmp,
    BoostUsage,
)


# --- get_or_create_boost_external_repo ---


@pytest.mark.django_db
def test_get_or_create_boost_external_repo_creates_new(external_github_repository):
    """get_or_create_boost_external_repo creates BoostExternalRepository and returns (repo, True)."""
    repo, created = services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version="1.83.0",
        is_boost_used=True,
    )
    assert created is True
    assert repo.pk == external_github_repository.pk
    assert isinstance(repo, BoostExternalRepository)
    assert repo.repo_name == external_github_repository.repo_name
    assert repo.boost_version == "1.83.0"
    assert repo.is_boost_used is True


@pytest.mark.django_db
def test_get_or_create_boost_external_repo_gets_existing(ext_repo, external_github_repository):
    """get_or_create_boost_external_repo returns existing and (repo, False)."""
    repo, created = services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version="1.84.0",
        is_boost_used=True,
    )
    assert created is False
    assert repo.pk == ext_repo.pk


@pytest.mark.django_db
def test_get_or_create_boost_external_repo_updates_flags(
    external_github_repository,
):
    """get_or_create_boost_external_repo updates boost_version and is_boost_embedded when existing."""
    services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version="1.80.0",
        is_boost_used=False,
    )
    repo2, created2 = services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version="1.81.0",
        is_boost_embedded=True,
        is_boost_used=True,
    )
    assert created2 is False
    repo2.refresh_from_db()
    assert repo2.boost_version == "1.81.0"
    assert repo2.is_boost_embedded is True
    assert repo2.is_boost_used is True


# --- update_boost_external_repo ---


@pytest.mark.django_db
def test_update_boost_external_repo_changes_boost_version(ext_repo):
    """update_boost_external_repo updates boost_version."""
    services.update_boost_external_repo(ext_repo, boost_version="1.85.0")
    ext_repo.refresh_from_db()
    assert ext_repo.boost_version == "1.85.0"


@pytest.mark.django_db
def test_update_boost_external_repo_changes_is_boost_used(ext_repo):
    """update_boost_external_repo updates is_boost_used."""
    services.update_boost_external_repo(ext_repo, is_boost_used=False)
    ext_repo.refresh_from_db()
    assert ext_repo.is_boost_used is False


@pytest.mark.django_db
def test_update_boost_external_repo_no_op_when_same(ext_repo):
    """update_boost_external_repo leaves DB unchanged when values match."""
    old_updated = ext_repo.updated_at
    result = services.update_boost_external_repo(
        ext_repo,
        boost_version=ext_repo.boost_version,
    )
    result.refresh_from_db()
    assert result.updated_at == old_updated


# --- create_or_update_boost_usage ---


@pytest.mark.django_db
def test_create_or_update_boost_usage_creates_new(
    ext_repo,
    boost_file,
    external_github_file,
):
    """create_or_update_boost_usage creates new record and returns (usage, True)."""
    usage, created = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
        last_commit_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    assert created is True
    assert usage.repo_id == ext_repo.pk
    assert usage.boost_header_id == boost_file.pk
    assert usage.file_path_id == external_github_file.pk
    assert usage.last_commit_date is not None
    assert usage.excepted_at is None


@pytest.mark.django_db
def test_create_or_update_boost_usage_gets_existing_and_updates(
    ext_repo,
    boost_file,
    external_github_file,
):
    """create_or_update_boost_usage returns existing and updates last_commit_date, clears excepted_at."""
    usage1, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
        last_commit_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    services.mark_usage_excepted(usage1)
    usage1.refresh_from_db()
    assert usage1.excepted_at is not None

    new_dt = datetime(2024, 7, 1, tzinfo=timezone.utc)
    usage2, created2 = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
        last_commit_date=new_dt,
    )
    assert created2 is False
    assert usage2.pk == usage1.pk
    usage2.refresh_from_db()
    assert usage2.last_commit_date == new_dt
    assert usage2.excepted_at is None


@pytest.mark.django_db
def test_create_or_update_boost_usage_idempotent(
    ext_repo,
    boost_file,
    external_github_file,
):
    """create_or_update_boost_usage same args returns existing."""
    services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    usage2, created2 = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    assert created2 is False
    assert BoostUsage.objects.filter(
        repo=ext_repo,
        boost_header=boost_file,
        file_path=external_github_file,
    ).count() == 1


# --- mark_usage_excepted ---


@pytest.mark.django_db
def test_mark_usage_excepted_sets_excepted_at(
    ext_repo,
    boost_file,
    external_github_file,
):
    """mark_usage_excepted sets excepted_at to today."""
    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    assert usage.excepted_at is None
    result = services.mark_usage_excepted(usage)
    result.refresh_from_db()
    assert result.excepted_at is not None


@pytest.mark.django_db
def test_mark_usage_excepted_idempotent(
    ext_repo,
    boost_file,
    external_github_file,
):
    """mark_usage_excepted called twice does not change excepted_at again."""
    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    services.mark_usage_excepted(usage)
    usage.refresh_from_db()
    first_date = usage.excepted_at
    services.mark_usage_excepted(usage)
    usage.refresh_from_db()
    assert usage.excepted_at == first_date


# --- get_active_usages_for_repo ---


@pytest.mark.django_db
def test_get_active_usages_for_repo_returns_non_excepted(
    ext_repo,
    boost_file,
    external_github_file,
):
    """get_active_usages_for_repo returns usages with excepted_at null."""
    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    active = services.get_active_usages_for_repo(ext_repo)
    assert len(active) == 1
    assert active[0].pk == usage.pk


@pytest.mark.django_db
def test_get_active_usages_for_repo_excludes_excepted(
    ext_repo,
    boost_file,
    external_github_file,
):
    """get_active_usages_for_repo excludes usages with excepted_at set."""
    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    services.mark_usage_excepted(usage)
    active = services.get_active_usages_for_repo(ext_repo)
    assert len(active) == 0


# --- get_or_create_missing_header_usage ---


@pytest.mark.django_db
def test_get_or_create_missing_header_usage_creates_new(
    ext_repo,
    external_github_file,
):
    """get_or_create_missing_header_usage creates placeholder usage and tmp, returns (usage, tmp, True)."""
    usage, tmp, created_tmp = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/unknown/header.hpp",
        last_commit_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
    )
    assert created_tmp is True
    assert usage.boost_header_id is None
    assert usage.repo_id == ext_repo.pk
    assert usage.file_path_id == external_github_file.pk
    assert tmp.usage_id == usage.pk
    assert tmp.header_name == "boost/unknown/header.hpp"


@pytest.mark.django_db
def test_get_or_create_missing_header_usage_gets_existing_tmp(
    ext_repo,
    external_github_file,
):
    """get_or_create_missing_header_usage returns existing tmp and (usage, tmp, False)."""
    services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/same.hpp",
    )
    usage2, tmp2, created2 = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/same.hpp",
    )
    assert created2 is False
    assert BoostMissingHeaderTmp.objects.filter(
        usage=usage2,
        header_name="boost/same.hpp",
    ).count() == 1


@pytest.mark.django_db
def test_get_or_create_missing_header_usage_updates_last_commit_date(
    ext_repo,
    external_github_file,
):
    """get_or_create_missing_header_usage updates usage last_commit_date when existing."""
    services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/other.hpp",
        last_commit_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    new_dt = datetime(2024, 8, 1, tzinfo=timezone.utc)
    usage, _, _ = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/other.hpp",
        last_commit_date=new_dt,
    )
    usage.refresh_from_db()
    assert usage.last_commit_date == new_dt
