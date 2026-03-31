"""Tests for clang_github_tracker.services."""

from datetime import timedelta

import pytest
from django.utils import timezone

from clang_github_tracker import services as clang_services
from clang_github_tracker.models import ClangGithubIssueItem


@pytest.mark.django_db
def test_upsert_issue_item_create_and_update_bumps_updated_at():
    t0 = timezone.now() - timedelta(days=2)
    t1 = timezone.now() - timedelta(days=1)
    _, created = clang_services.upsert_issue_item(
        42,
        is_pull_request=False,
        github_created_at=t0,
        github_updated_at=t0,
    )
    assert created is True
    row = ClangGithubIssueItem.objects.get(number=42)
    first_updated = row.updated_at

    _, created2 = clang_services.upsert_issue_item(
        42,
        is_pull_request=False,
        github_created_at=t0,
        github_updated_at=t1,
    )
    assert created2 is False
    row.refresh_from_db()
    assert row.updated_at > first_updated
    assert row.github_updated_at == t1


@pytest.mark.django_db
def test_watermarks_empty():
    assert clang_services.get_issue_item_watermark() is None
    assert clang_services.get_commit_watermark() is None
    assert clang_services.start_after_watermark(None) is None
