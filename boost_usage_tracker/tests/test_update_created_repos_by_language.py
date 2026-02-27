"""Tests for boost_usage_tracker.update_created_repos_by_language."""

from unittest.mock import patch

import pytest
from model_bakery import baker

from boost_usage_tracker.update_created_repos_by_language import (
    update_created_repos_by_language,
)
from github_activity_tracker.models import CreatedReposByLanguage


@pytest.mark.django_db
def test_update_created_repos_by_language_requires_languages():
    """Returns error when no env/arg languages are provided."""
    with patch.dict("os.environ", {"REPO_COUNT_LANGUAGES": ""}, clear=False):
        result = update_created_repos_by_language(
            languages_csv="",
            start_year=2024,
            end_year=2024,
        )
    assert result["rows_processed"] == 0
    assert result["errors"]


@pytest.mark.django_db
def test_update_created_repos_by_language_upserts_rows():
    """Upserts yearly rows for languages existing in Language table."""
    cpp = baker.make("github_activity_tracker.Language", name="C++")

    def fake_count(_client, query: str) -> int:
        if "stars:>10" in query:
            return 12
        return 120

    with patch(
        "boost_usage_tracker.update_created_repos_by_language.get_github_client"
    ), patch(
        "boost_usage_tracker.update_created_repos_by_language._count_items_from_git",
        side_effect=fake_count,
    ):
        result = update_created_repos_by_language(
            languages_csv="C++",
            start_year=2024,
            end_year=2025,
            stars_min=10,
        )

    assert result["errors"] == []
    assert result["rows_processed"] == 2
    assert result["created"] == 2
    assert result["updated"] == 0

    rows = list(
        CreatedReposByLanguage.objects.filter(  # pylint: disable=no-member
            language=cpp
        ).order_by("year")
    )
    assert [r.year for r in rows] == [2024, 2025]
    assert all(r.all_repos == 120 for r in rows)
    assert all(r.significant_repos == 12 for r in rows)

    # second run updates existing rows
    with patch(
        "boost_usage_tracker.update_created_repos_by_language.get_github_client"
    ), patch(
        "boost_usage_tracker.update_created_repos_by_language._count_items_from_git",
        side_effect=lambda _client, q: 130 if "stars:>10" not in q else 13,
    ):
        second = update_created_repos_by_language(
            languages_csv="C++",
            start_year=2024,
            end_year=2025,
            stars_min=10,
        )

    assert second["created"] == 0
    assert second["updated"] == 2
    rows = list(
        CreatedReposByLanguage.objects.filter(  # pylint: disable=no-member
            language=cpp
        ).order_by("year")
    )
    assert all(r.all_repos == 130 for r in rows)
    assert all(r.significant_repos == 13 for r in rows)
