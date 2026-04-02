"""Tests for clang_github_tracker.services."""

from datetime import timedelta

import pytest
from django.utils import timezone

from clang_github_tracker import services as clang_services
from clang_github_tracker.models import ClangGithubCommit, ClangGithubIssueItem


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


@pytest.mark.django_db
def test_upsert_commits_batch_create_and_update():
    sha_a = "a" * 40
    sha_b = "b" * 40
    t0 = timezone.now() - timedelta(days=1)
    t1 = timezone.now()
    ins, upd = clang_services.upsert_commits_batch([(sha_a, t0), (sha_b, t0)])
    assert ins == 2 and upd == 0
    row = ClangGithubCommit.objects.get(sha=sha_a)
    first_updated = row.updated_at
    ins2, upd2 = clang_services.upsert_commits_batch([(sha_a, t1)])
    assert ins2 == 0 and upd2 == 1
    row.refresh_from_db()
    assert row.github_committed_at == t1
    assert row.updated_at > first_updated


@pytest.mark.django_db
def test_upsert_issue_items_batch_create_and_update():
    t0 = timezone.now() - timedelta(days=2)
    t1 = timezone.now() - timedelta(days=1)
    ins, upd = clang_services.upsert_issue_items_batch(
        [(10, False, t0, t0), (11, True, t0, t0)]
    )
    assert ins == 2 and upd == 0
    row = ClangGithubIssueItem.objects.get(number=10)
    first_updated = row.updated_at
    ins2, upd2 = clang_services.upsert_issue_items_batch([(10, False, t0, t1)])
    assert ins2 == 0 and upd2 == 1
    row.refresh_from_db()
    assert row.github_updated_at == t1
    assert row.updated_at > first_updated
