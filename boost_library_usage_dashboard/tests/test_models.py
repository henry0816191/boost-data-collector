"""Model contract tests for boost_library_usage_dashboard."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from boost_library_usage_dashboard.models import BoostExternalRepository, BoostUsage
from boost_usage_tracker import models as usage_models


def test_boost_external_repository_meta_contract():
    assert BoostExternalRepository is usage_models.BoostExternalRepository
    assert (
        BoostExternalRepository._meta.db_table
        == "boost_usage_tracker_boostexternalrepository"
    )


def test_boost_usage_meta_contract():
    assert BoostUsage is usage_models.BoostUsage
    assert BoostUsage._meta.db_table == "boost_usage_tracker_boostusage"


# Exclude inherited GitHubRepository required fields when validating only BoostExternalRepository fields.
_BOOST_EXT_REPO_EXCLUDE = [
    "githubrepository_ptr",
    "owner_account",
    "repo_name",
    "created_at",
    "updated_at",
]


def test_boost_external_repository_boost_version_allows_empty_string():
    obj = BoostExternalRepository(boost_version="")
    obj.full_clean(exclude=_BOOST_EXT_REPO_EXCLUDE)


def test_boost_external_repository_boost_version_max_boundary_valid():
    obj = BoostExternalRepository(boost_version="x" * 64)
    obj.full_clean(exclude=_BOOST_EXT_REPO_EXCLUDE)


def test_boost_external_repository_boost_version_over_max_invalid():
    obj = BoostExternalRepository(boost_version="x" * 65)
    with pytest.raises(ValidationError):
        obj.full_clean(exclude=_BOOST_EXT_REPO_EXCLUDE)


def test_boost_usage_optional_fields_allow_null():
    obj = BoostUsage(
        last_commit_date=None,
        excepted_at=None,
        boost_header=None,
    )
    obj.full_clean(exclude=["repo", "file_path", "created_at", "updated_at"])


def test_boost_usage_excepted_at_accepts_valid_date():
    obj = BoostUsage(excepted_at=date(2026, 1, 1))
    obj.full_clean(
        exclude=["repo", "file_path", "created_at", "updated_at", "boost_header"]
    )
