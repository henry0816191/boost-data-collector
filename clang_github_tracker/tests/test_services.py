"""Tests for clang_github_tracker.services."""

from datetime import timedelta

import pytest
from django.utils import timezone

from clang_github_tracker import services as clang_services
from clang_github_tracker.models import ClangGithubCommit, ClangGithubIssueItem


@pytest.mark.django_db
def test_upsert_issue_item_rejects_bool_and_non_positive():
    t0 = timezone.now()
    with pytest.raises(ValueError, match="positive integer"):
        clang_services.upsert_issue_item(
            True,
            is_pull_request=False,
            github_created_at=t0,
            github_updated_at=t0,
        )
    with pytest.raises(ValueError, match="positive integer"):
        clang_services.upsert_issue_item(
            0,
            is_pull_request=False,
            github_created_at=t0,
            github_updated_at=t0,
        )
    assert ClangGithubIssueItem.objects.count() == 0


@pytest.mark.django_db
def test_upsert_issue_items_batch_skips_bool_does_not_upsert_as_issue_one():
    t0 = timezone.now()
    ins, _ = clang_services.upsert_issue_items_batch([(True, False, t0, t0)])
    assert ins == 0
    assert not ClangGithubIssueItem.objects.filter(number=1).exists()


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
    assert row.github_updated_at == t1
    assert row.updated_at >= first_updated


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
    assert row.updated_at >= first_updated


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
    assert row.updated_at >= first_updated


@pytest.mark.django_db
def test_upsert_commits_batch_dedupes_sha_by_case():
    """Uppercase and lowercase hex refer to the same commit; merge timestamps in one row."""
    sha_lower = "abcdef" + "0" * 34
    sha_upper = "ABCDEF" + "0" * 34
    t_new = timezone.now()
    t_old = t_new - timedelta(days=7)
    ins, _ = clang_services.upsert_commits_batch(
        [(sha_upper, t_old), (sha_lower, t_new)]
    )
    assert ins == 1
    assert ClangGithubCommit.objects.count() == 1
    row = ClangGithubCommit.objects.get(sha=sha_lower)
    assert row.github_committed_at == t_new


@pytest.mark.django_db
def test_upsert_commit_canonicalizes_sha_to_lowercase():
    sha_mixed = "AbCdEf" + "0" * 34
    t0 = timezone.now()
    clang_services.upsert_commit(sha_mixed, github_committed_at=t0)
    row = ClangGithubCommit.objects.get(sha=sha_mixed.lower())
    assert row.github_committed_at == t0


@pytest.mark.django_db
def test_upsert_commits_batch_duplicate_sha_keeps_latest_committed_at():
    sha = "c" * 40
    t_new = timezone.now()
    t_old = t_new - timedelta(days=7)
    clang_services.upsert_commits_batch([(sha, t_new), (sha, t_old)])
    row = ClangGithubCommit.objects.get(sha=sha)
    assert row.github_committed_at == t_new


@pytest.mark.django_db
def test_upsert_commits_batch_duplicate_sha_none_does_not_wipe_timestamp():
    sha = "d" * 40
    t0 = timezone.now() - timedelta(hours=1)
    clang_services.upsert_commits_batch([(sha, t0), (sha, None)])
    assert ClangGithubCommit.objects.get(sha=sha).github_committed_at == t0


@pytest.mark.django_db
def test_upsert_issue_items_batch_duplicate_number_keeps_latest_github_updated_at():
    t_base = timezone.now() - timedelta(days=5)
    t_new = timezone.now()
    t_old = t_new - timedelta(days=1)
    clang_services.upsert_issue_items_batch(
        [
            (7, False, t_base, t_new),
            (7, False, t_base, t_old),
        ]
    )
    row = ClangGithubIssueItem.objects.get(number=7)
    assert row.github_updated_at == t_new


@pytest.mark.django_db
def test_upsert_issue_items_batch_duplicate_merges_is_pr_or():
    t0 = timezone.now() - timedelta(days=1)
    clang_services.upsert_issue_items_batch([(8, False, t0, t0), (8, True, t0, t0)])
    assert ClangGithubIssueItem.objects.get(number=8).is_pull_request is True


@pytest.mark.django_db
def test_upsert_issue_item_merge_keeps_pr_and_timestamps_when_incoming_partial():
    t_created = timezone.now() - timedelta(days=10)
    t_updated = timezone.now() - timedelta(days=3)
    clang_services.upsert_issue_item(
        99,
        is_pull_request=True,
        github_created_at=t_created,
        github_updated_at=t_updated,
    )
    clang_services.upsert_issue_item(
        99,
        is_pull_request=False,
        github_created_at=None,
        github_updated_at=None,
    )
    row = ClangGithubIssueItem.objects.get(number=99)
    assert row.is_pull_request is True
    assert row.github_created_at == t_created
    assert row.github_updated_at == t_updated


@pytest.mark.django_db
def test_upsert_issue_item_merge_github_updated_at_max():
    t_old = timezone.now() - timedelta(days=5)
    t_new = timezone.now() - timedelta(days=1)
    clang_services.upsert_issue_item(
        100,
        is_pull_request=False,
        github_created_at=t_old,
        github_updated_at=t_new,
    )
    clang_services.upsert_issue_item(
        100,
        is_pull_request=False,
        github_created_at=None,
        github_updated_at=t_old,
    )
    assert ClangGithubIssueItem.objects.get(number=100).github_updated_at == t_new


@pytest.mark.django_db
def test_upsert_commit_merge_preserves_committed_at_when_incoming_none():
    sha = "e" * 40
    t0 = timezone.now() - timedelta(hours=2)
    clang_services.upsert_commit(sha, github_committed_at=t0)
    clang_services.upsert_commit(sha, github_committed_at=None)
    assert ClangGithubCommit.objects.get(sha=sha).github_committed_at == t0


@pytest.mark.django_db
def test_upsert_issue_items_batch_merge_with_db_preserves_updated_when_incoming_none():
    t0 = timezone.now() - timedelta(days=2)
    t1 = timezone.now() - timedelta(days=1)
    clang_services.upsert_issue_items_batch([(20, False, t0, t1)])
    clang_services.upsert_issue_items_batch([(20, False, None, None)])
    row = ClangGithubIssueItem.objects.get(number=20)
    assert row.github_created_at == t0
    assert row.github_updated_at == t1
    assert row.is_pull_request is False


@pytest.mark.django_db
def test_upsert_issue_items_batch_merge_with_db_keeps_pr_once_true():
    t0 = timezone.now() - timedelta(days=1)
    clang_services.upsert_issue_items_batch([(21, True, t0, t0)])
    clang_services.upsert_issue_items_batch([(21, False, t0, t0)])
    assert ClangGithubIssueItem.objects.get(number=21).is_pull_request is True
