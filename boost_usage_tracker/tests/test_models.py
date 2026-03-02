"""Tests for boost_usage_tracker models.

Covers models in detail including edge cases and boundaries:
- Empty inputs, maximum/minimum values, invalid or unexpected data.
- Meta options, constraints, and relations.
"""

import pytest
from django.db import IntegrityError, transaction

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


# --- BoostExternalRepository: edge cases and boundaries ---


@pytest.mark.django_db
def test_boost_external_repository_empty_boost_version(external_github_repository):
    """BoostExternalRepository allows empty boost_version (blank=True)."""
    from boost_usage_tracker import services

    repo, _ = services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version="",
        is_boost_used=False,
    )
    assert repo.boost_version == ""
    repo.refresh_from_db()
    assert repo.boost_version == ""


@pytest.mark.django_db
def test_boost_external_repository_boost_version_max_length(external_github_repository):
    """BoostExternalRepository accepts boost_version up to max_length=64."""
    from boost_usage_tracker import services

    max_version = "1." + "9" * 62  # 64 chars
    assert len(max_version) == 64
    repo, _ = services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version=max_version,
        is_boost_used=True,
    )
    repo.refresh_from_db()
    assert repo.boost_version == max_version


@pytest.mark.django_db
def test_boost_external_repository_default_bools(external_github_repository):
    """BoostExternalRepository defaults: is_boost_embedded=False, is_boost_used=False."""
    from boost_usage_tracker import services

    repo, _ = services.get_or_create_boost_external_repo(
        external_github_repository,
        boost_version="1.80.0",
    )
    assert repo.is_boost_embedded is False
    assert repo.is_boost_used is False


@pytest.mark.django_db
def test_boost_external_repository_meta_db_table():
    """BoostExternalRepository uses correct db_table."""
    assert (
        BoostExternalRepository._meta.db_table
        == "boost_usage_tracker_boostexternalrepository"
    )


@pytest.mark.django_db
def test_boost_external_repository_meta_verbose_names():
    """BoostExternalRepository has correct verbose_name and verbose_name_plural."""
    assert BoostExternalRepository._meta.verbose_name == "Boost External Repository"
    assert (
        BoostExternalRepository._meta.verbose_name_plural
        == "Boost External Repositories"
    )


@pytest.mark.django_db
def test_boost_external_repository_boost_version_field_blank():
    """BoostExternalRepository.boost_version is blank=True (no required validation)."""
    field = BoostExternalRepository._meta.get_field("boost_version")
    assert field.blank is True
    assert field.max_length == 64


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
    assert (
        BoostUsage.objects.filter(
            repo=ext_repo,
            boost_header=boost_file,
            file_path=external_github_file,
        ).count()
        == 1
    )


# --- BoostUsage: edge cases and boundaries ---


@pytest.mark.django_db
def test_boost_usage_last_commit_date_nullable(
    ext_repo,
    boost_file,
    external_github_file,
):
    """BoostUsage allows last_commit_date to be None (null=True, blank=True)."""
    from boost_usage_tracker import services

    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
        last_commit_date=None,
    )
    assert usage.last_commit_date is None
    usage.refresh_from_db()
    assert usage.last_commit_date is None


@pytest.mark.django_db
def test_boost_usage_excepted_at_nullable(
    ext_repo,
    boost_file,
    external_github_file,
):
    """BoostUsage allows excepted_at to be None (null=True, blank=True)."""
    from boost_usage_tracker import services

    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    assert usage.excepted_at is None


@pytest.mark.django_db
def test_boost_usage_unique_repo_file_path_when_boost_header_null(
    ext_repo,
    external_github_file,
):
    """BoostUsage allows only one row per (repo, file_path) when boost_header is null."""
    from boost_usage_tracker import services

    usage1, tmp1, c1 = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/header_a.hpp",
    )
    usage2, tmp2, c2 = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/header_b.hpp",
    )
    assert usage1.pk == usage2.pk
    assert (
        BoostUsage.objects.filter(
            repo=ext_repo, file_path=external_github_file, boost_header__isnull=True
        ).count()
        == 1
    )
    assert BoostMissingHeaderTmp.objects.filter(usage=usage1).count() == 2


@pytest.mark.django_db
def test_boost_usage_duplicate_repo_header_file_raises_integrity_error(
    ext_repo,
    boost_file,
    external_github_file,
):
    """Creating duplicate (repo, boost_header, file_path) via ORM raises IntegrityError."""
    from boost_usage_tracker import services

    services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            BoostUsage.objects.create(
                repo=ext_repo,
                boost_header=boost_file,
                file_path=external_github_file,
            )


@pytest.mark.django_db
def test_boost_usage_meta_db_table():
    """BoostUsage uses correct db_table."""
    assert BoostUsage._meta.db_table == "boost_usage_tracker_boostusage"


@pytest.mark.django_db
def test_boost_usage_meta_ordering():
    """BoostUsage Meta ordering is (repo, boost_header, file_path)."""
    assert BoostUsage._meta.ordering == ["repo", "boost_header", "file_path"]


@pytest.mark.django_db
def test_boost_usage_related_boost_usages_on_repo(
    ext_repo,
    boost_file,
    external_github_file,
):
    """BoostUsage is accessible via repo.boost_usages."""
    from boost_usage_tracker import services

    usage, _ = services.create_or_update_boost_usage(
        ext_repo,
        boost_file,
        external_github_file,
    )
    assert usage in ext_repo.boost_usages.all()
    assert ext_repo.boost_usages.filter(boost_header=boost_file).count() == 1


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
    assert (
        BoostMissingHeaderTmp.objects.filter(
            usage__repo=ext_repo,
            header_name="boost/unique.hpp",
        ).count()
        == 1
    )


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


# --- BoostMissingHeaderTmp: edge cases and boundaries ---


@pytest.mark.django_db
def test_boost_missing_header_tmp_header_name_max_length(
    ext_repo,
    external_github_file,
):
    """BoostMissingHeaderTmp accepts header_name up to max_length=512."""
    from boost_usage_tracker import services

    long_header = "boost/" + "x" * 506  # 6 + 506 = 512 chars total
    assert len(long_header) == 512
    _, tmp, _ = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        long_header,
    )
    tmp.refresh_from_db()
    assert tmp.header_name == long_header


@pytest.mark.django_db
def test_boost_missing_header_tmp_multiple_headers_same_usage(
    ext_repo,
    external_github_file,
):
    """One usage (boost_header=null) can have multiple BoostMissingHeaderTmp rows."""
    from boost_usage_tracker import services

    usage, tmp1, c1 = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/one.hpp",
    )
    _, tmp2, c2 = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/two.hpp",
    )
    assert usage.pk == tmp1.usage_id == tmp2.usage_id
    assert BoostMissingHeaderTmp.objects.filter(usage=usage).count() == 2
    assert set(
        BoostMissingHeaderTmp.objects.filter(usage=usage).values_list(
            "header_name", flat=True
        )
    ) == {
        "boost/one.hpp",
        "boost/two.hpp",
    }


@pytest.mark.django_db
def test_boost_missing_header_tmp_duplicate_usage_header_raises_integrity_error(
    ext_repo,
    external_github_file,
):
    """Creating duplicate (usage, header_name) via ORM raises IntegrityError."""
    from boost_usage_tracker import services

    usage, tmp, _ = services.get_or_create_missing_header_usage(
        ext_repo,
        external_github_file,
        "boost/dup.hpp",
    )
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            BoostMissingHeaderTmp.objects.create(
                usage=usage,
                header_name="boost/dup.hpp",
            )


@pytest.mark.django_db
def test_boost_missing_header_tmp_meta_db_table():
    """BoostMissingHeaderTmp uses correct db_table."""
    assert (
        BoostMissingHeaderTmp._meta.db_table
        == "boost_usage_tracker_boostmissingheadertmp"
    )


@pytest.mark.django_db
def test_boost_missing_header_tmp_meta_ordering():
    """BoostMissingHeaderTmp Meta ordering is (usage, header_name)."""
    assert BoostMissingHeaderTmp._meta.ordering == ["usage", "header_name"]


@pytest.mark.django_db
def test_boost_missing_header_tmp_header_name_not_blank():
    """BoostMissingHeaderTmp.header_name is not blank (required)."""
    field = BoostMissingHeaderTmp._meta.get_field("header_name")
    assert field.blank is False
    assert field.max_length == 512
