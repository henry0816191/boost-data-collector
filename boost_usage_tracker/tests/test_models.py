"""Tests for boost_usage_tracker models."""

import pytest
from model_bakery import baker

from boost_usage_tracker.models import (
    BoostExternalRepository,
    BoostMissingHeaderTmp,
    BoostUsage,
)


# --- BoostExternalRepository ---


@pytest.mark.django_db
def test_boost_external_repository_extends_github_repo(
    ext_repo,
    external_github_repository,
):
    """BoostExternalRepository uses same PK as parent GitHubRepository."""
    assert ext_repo.pk == external_github_repository.pk
    assert ext_repo.repo_name == external_github_repository.repo_name


@pytest.mark.django_db
def test_boost_external_repository_has_extra_fields(ext_repo):
    """BoostExternalRepository has boost_version, is_boost_embedded, is_boost_used."""
    assert ext_repo.boost_version == "1.84.0"
    assert ext_repo.is_boost_used is True
    assert ext_repo.is_boost_embedded is False


@pytest.mark.django_db
def test_boost_external_repository_has_timestamps(ext_repo):
    """BoostExternalRepository has created_at and updated_at."""
    assert ext_repo.created_at is not None
    assert ext_repo.updated_at is not None


@pytest.mark.django_db
def test_boost_external_repository_ordering():
    """BoostExternalRepository Meta ordering is repo_name."""
    assert BoostExternalRepository._meta.ordering == ["repo_name"]


# --- BoostUsage ---


@pytest.mark.django_db
def test_boost_usage_links_repo_header_and_file(
    ext_repo,
    boost_file,
    external_github_file,
):
    """BoostUsage links repo, boost_header, and file_path."""
    from boost_usage_tracker import services

    usage, created = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    assert created is True
    assert usage.repo_id == ext_repo.pk
    assert usage.boost_header_id == boost_file.pk
    assert usage.file_path_id == external_github_file.pk


@pytest.mark.django_db
def test_boost_usage_boost_header_nullable(
    ext_repo,
    external_github_file,
):
    """BoostUsage allows boost_header=null (placeholder for missing-header tmp)."""
    from boost_usage_tracker import services

    usage, tmp, _ = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/unknown/header.hpp",
    )
    assert usage.boost_header_id is None
    assert usage.repo_id == ext_repo.pk
    assert usage.file_path_id == external_github_file.pk


@pytest.mark.django_db
def test_boost_usage_has_timestamps(
    ext_repo,
    boost_file,
    external_github_file,
):
    """BoostUsage has last_commit_date, excepted_at, created_at, updated_at."""
    from boost_usage_tracker import services

    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    assert usage.created_at is not None
    assert usage.updated_at is not None
    assert usage.excepted_at is None


@pytest.mark.django_db
def test_boost_usage_unique_repo_header_file(
    ext_repo,
    boost_file,
    external_github_file,
):
    """BoostUsage has unique constraint on (repo, boost_header, file_path)."""
    from boost_usage_tracker import services

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


# --- BoostMissingHeaderTmp ---


@pytest.mark.django_db
def test_boost_missing_header_tmp_links_usage_and_header_name(
    ext_repo,
    external_github_file,
):
    """BoostMissingHeaderTmp links usage_id to BoostUsage and stores header_name."""
    from boost_usage_tracker import services

    usage, tmp, created = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/some/missing.hpp",
    )
    assert created is True
    assert tmp.usage_id == usage.pk
    assert tmp.header_name == "boost/some/missing.hpp"


@pytest.mark.django_db
def test_boost_missing_header_tmp_has_created_at(
    ext_repo,
    external_github_file,
):
    """BoostMissingHeaderTmp has created_at."""
    from boost_usage_tracker import services

    _, tmp, _ = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/other.hpp",
    )
    assert tmp.created_at is not None


@pytest.mark.django_db
def test_boost_missing_header_tmp_unique_usage_header(
    ext_repo,
    external_github_file,
):
    """BoostMissingHeaderTmp has unique (usage, header_name)."""
    from boost_usage_tracker import services

    services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/unique.hpp",
    )
    _, tmp2, created2 = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/unique.hpp",
    )
    assert created2 is False
    assert BoostMissingHeaderTmp.objects.filter(
        usage__repo=ext_repo,
        header_name="boost/unique.hpp",
    ).count() == 1


@pytest.mark.django_db
def test_boost_missing_header_tmp_reverse_relation(
    ext_repo,
    external_github_file,
):
    """BoostMissingHeaderTmp accessible via usage.missing_header_tmp."""
    from boost_usage_tracker import services

    usage, tmp, _ = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/reverse.hpp",
    )
    assert tmp in usage.missing_header_tmp.all()
    assert usage.missing_header_tmp.filter(header_name="boost/reverse.hpp").exists()
