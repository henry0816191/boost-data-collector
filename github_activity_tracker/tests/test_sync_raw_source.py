"""Tests for github_activity_tracker.sync.raw_source."""

import json
import pytest
from unittest.mock import patch

from github_activity_tracker.sync.raw_source import (
    save_commit_raw_source,
    save_issue_raw_source,
    save_pr_raw_source,
)


@pytest.fixture
def raw_source_tmp(tmp_path):
    """Patch workspace path helpers so raw source writes go to tmp_path."""
    root = tmp_path / "raw" / "github_activity_tracker"
    with patch(
        "github_activity_tracker.sync.raw_source.get_raw_source_commit_path",
        side_effect=lambda o, r, sha: root / o / r / "commits" / f"{sha}.json",
    ), patch(
        "github_activity_tracker.sync.raw_source.get_raw_source_issue_path",
        side_effect=lambda o, r, num: root / o / r / "issues" / f"{num}.json",
    ), patch(
        "github_activity_tracker.sync.raw_source.get_raw_source_pr_path",
        side_effect=lambda o, r, num: root / o / r / "prs" / f"{num}.json",
    ):
        yield root


def test_save_commit_raw_source_writes_file(raw_source_tmp):
    """save_commit_raw_source writes commit JSON to commits/<sha>.json."""
    save_commit_raw_source(
        "owner", "repo", {"sha": "abc123", "commit": {"message": "fix"}}
    )
    path = raw_source_tmp / "owner" / "repo" / "commits" / "abc123.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["sha"] == "abc123"
    assert data["commit"]["message"] == "fix"


def test_save_commit_raw_source_skips_empty_sha(raw_source_tmp):
    """save_commit_raw_source does not write when sha is missing or empty."""
    save_commit_raw_source("owner", "repo", {})
    commits_dir = raw_source_tmp / "owner" / "repo" / "commits"
    assert not commits_dir.exists() or list(commits_dir.iterdir()) == []


def test_save_issue_raw_source_merges_comments_by_id(raw_source_tmp):
    """save_issue_raw_source merges existing and new comments by id (new wins)."""
    path = raw_source_tmp / "owner" / "repo" / "issues" / "1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "number": 1,
                "title": "Old",
                "comments": [{"id": 10, "body": "old comment"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    save_issue_raw_source(
        "owner",
        "repo",
        {
            "number": 1,
            "title": "New",
            "comments": [{"id": 10, "body": "updated"}, {"id": 11, "body": "new"}],
        },
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "New"
    assert len(data["comments"]) == 2
    by_id = {c["id"]: c["body"] for c in data["comments"]}
    assert by_id[10] == "updated"
    assert by_id[11] == "new"


def test_save_issue_raw_source_writes_new_file(raw_source_tmp):
    """save_issue_raw_source writes new issue JSON when file does not exist."""
    save_issue_raw_source(
        "owner", "repo", {"number": 2, "title": "Issue 2", "comments": []}
    )
    path = raw_source_tmp / "owner" / "repo" / "issues" / "2.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["number"] == 2
    assert data["comments"] == []


def test_save_pr_raw_source_merges_comments_and_reviews_by_id(raw_source_tmp):
    """save_pr_raw_source merges comments and reviews by id (new wins)."""
    path = raw_source_tmp / "owner" / "repo" / "prs" / "1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "number": 1,
                "title": "Old",
                "comments": [{"id": 20, "body": "old"}],
                "reviews": [{"id": 30, "state": "CHANGES_REQUESTED"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    save_pr_raw_source(
        "owner",
        "repo",
        {
            "number": 1,
            "title": "New",
            "comments": [{"id": 20, "body": "updated"}],
            "reviews": [{"id": 30, "state": "APPROVED"}, {"id": 31, "body": "LGTM"}],
        },
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "New"
    assert len(data["comments"]) == 1
    assert data["comments"][0]["body"] == "updated"
    assert len(data["reviews"]) == 2
    by_id = {r["id"]: r.get("state") or r.get("body") for r in data["reviews"]}
    assert by_id[30] == "APPROVED"
    assert by_id[31] == "LGTM"


def test_save_pr_raw_source_writes_new_file(raw_source_tmp):
    """save_pr_raw_source writes new PR JSON when file does not exist."""
    save_pr_raw_source(
        "owner",
        "repo",
        {"number": 3, "title": "PR 3", "comments": [], "reviews": []},
    )
    path = raw_source_tmp / "owner" / "repo" / "prs" / "3.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["number"] == 3
    assert data["comments"] == []
    assert data["reviews"] == []
