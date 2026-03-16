"""Tests for operations.md_ops converters: issue_json_to_md and pr_json_to_md."""

from operations.md_ops.issue_to_md import issue_json_to_md
from operations.md_ops.pr_to_md import pr_json_to_md


# --- issue_json_to_md ---


def test_issue_json_to_md_minimal():
    """Minimal issue (issue_info only) produces title, metadata block, and body."""
    data = {
        "issue_info": {
            "number": 42,
            "title": "Fix the bug",
            "state": "open",
            "user": {"login": "alice"},
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T11:00:00Z",
            "html_url": "https://github.com/org/repo/issues/42",
            "body": "Description here.",
        },
        "comments": [],
    }
    md = issue_json_to_md(data)
    assert "# #42 - Fix the bug [Open]" in md
    assert "> Username: alice  " in md
    assert "> Created at: 2024-01-15 10:00:00 UTC" in md
    assert "> Url: https://github.com/org/repo/issues/42" in md
    assert "Description here." in md
    assert md.endswith("\n")


def test_issue_json_to_md_closed():
    """Closed issue shows [Closed] and closed_at in metadata."""
    data = {
        "issue_info": {
            "number": 1,
            "title": "Done",
            "state": "closed",
            "user": {"login": "bob"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "closed_at": "2024-01-02T12:00:00Z",
            "html_url": "https://example.com/issue/1",
            "body": "",
        },
        "comments": [],
    }
    md = issue_json_to_md(data)
    assert "# #1 - Done [Closed]" in md
    assert "> Closed at: 2024-01-02 12:00:00 UTC" in md


def test_issue_json_to_md_with_comments():
    """Issue with comments includes Comment 1, Comment 2 sections."""
    data = {
        "issue_info": {
            "number": 10,
            "title": "Question",
            "state": "open",
            "user": {"login": "user1"},
            "created_at": "2024-06-01T09:00:00Z",
            "updated_at": "2024-06-01T09:00:00Z",
            "body": "Initial post.",
        },
        "comments": [
            {
                "user": {"login": "user2"},
                "created_at": "2024-06-01T10:00:00Z",
                "updated_at": "2024-06-01T10:00:00Z",
                "body": "First reply.",
            },
            {
                "user": {"login": "user3"},
                "created_at": "2024-06-01T11:00:00Z",
                "updated_at": "2024-06-01T11:00:00Z",
                "body": "Second reply.",
            },
        ],
    }
    md = issue_json_to_md(data)
    assert "Initial post." in md
    assert "## Comment 1" in md
    assert "First reply." in md
    assert "## Comment 2" in md
    assert "Second reply." in md
    assert "> Username: user2  " in md
    assert "> Username: user3  " in md


def test_issue_json_to_md_missing_issue_info_uses_defaults():
    """Empty or missing issue_info uses defaults for number, title, state, user."""
    data = {"issue_info": {}, "comments": []}
    md = issue_json_to_md(data)
    assert "# #? - " in md
    assert "[Open]" in md
    assert "> Username: unknown  " in md


# --- pr_json_to_md ---


def test_pr_json_to_md_minimal():
    """Minimal PR (pr_info only) produces header, metadata, and body."""
    data = {
        "pr_info": {
            "number": 100,
            "title": "Add feature",
            "state": "open",
            "merged": False,
            "user": {"login": "dev"},
            "created_at": "2024-03-01T08:00:00Z",
            "updated_at": "2024-03-02T09:00:00Z",
            "html_url": "https://github.com/org/repo/pull/100",
            "body": "This PR adds X.",
        },
        "reviews": [],
        "comments": [],
    }
    md = pr_json_to_md(data)
    assert "# #100 Add feature [Open]" in md
    assert "> Username: dev  " in md
    assert "> Created at: 2024-03-01 08:00:00 UTC" in md
    assert "> Url: https://github.com/org/repo/pull/100" in md
    assert "This PR adds X." in md
    assert "---" in md


def test_pr_json_to_md_merged():
    """Merged PR shows [Merged] and merged_at in metadata."""
    data = {
        "pr_info": {
            "number": 50,
            "title": "Merge it",
            "state": "closed",
            "merged": True,
            "user": {"login": "maintainer"},
            "created_at": "2024-02-01T00:00:00Z",
            "updated_at": "2024-02-02T00:00:00Z",
            "merged_at": "2024-02-02T15:30:00Z",
            "closed_at": "2024-02-02T15:30:00Z",
            "html_url": "https://github.com/org/repo/pull/50",
            "body": "Done.",
        },
        "reviews": [],
        "comments": [],
    }
    md = pr_json_to_md(data)
    assert "# #50 Merge it [Merged]" in md
    assert "> Merged at: 2024-02-02 15:30:00 UTC" in md


def test_pr_json_to_md_with_comment():
    """PR with one regular comment includes Comment 1 section."""
    data = {
        "pr_info": {
            "number": 1,
            "title": "PR",
            "state": "open",
            "merged": False,
            "user": {"login": "author"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "body": "PR body.",
        },
        "reviews": [],
        "comments": [
            {
                "user": {"login": "reviewer"},
                "created_at": "2024-01-01T12:00:00Z",
                "body": "LGTM",
                "pull_request_review_id": None,
            },
        ],
    }
    md = pr_json_to_md(data)
    assert "## Comment 1" in md
    assert "LGTM" in md
    assert "> Username: reviewer  " in md


def test_pr_json_to_md_with_review():
    """PR with a review includes Review section and state tag."""
    data = {
        "pr_info": {
            "number": 2,
            "title": "Change",
            "state": "open",
            "merged": False,
            "user": {"login": "author"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "body": "Body",
        },
        "reviews": [
            {
                "id": 99,
                "user": {"login": "reviewer"},
                "state": "APPROVED",
                "submitted_at": "2024-01-01T14:00:00Z",
                "body": "Looks good.",
                "html_url": "https://github.com/org/repo/pull/2#pullrequestreview-99",
            },
        ],
        "comments": [],
    }
    md = pr_json_to_md(data)
    assert "## Review 1 [Approved]" in md
    assert "Looks good." in md
    assert "> State: APPROVED  " in md


def test_pr_json_to_md_with_reviews_and_comments():
    """PR with both reviews and comments includes Comment and Review sections."""
    data = {
        "pr_info": {
            "number": 5,
            "title": "Feature PR",
            "state": "open",
            "merged": False,
            "user": {"login": "author"},
            "created_at": "2024-01-01T09:00:00Z",
            "updated_at": "2024-01-01T09:00:00Z",
            "body": "PR description.",
        },
        "reviews": [
            {
                "id": 101,
                "user": {"login": "reviewer1"},
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2024-01-01T11:00:00Z",
                "body": "Please fix the typo.",
                "html_url": "https://github.com/org/repo/pull/5#pullrequestreview-101",
            },
        ],
        "comments": [
            {
                "user": {"login": "collaborator"},
                "created_at": "2024-01-01T10:00:00Z",
                "body": "I have a question about the approach.",
                "pull_request_review_id": None,
            },
        ],
    }
    md = pr_json_to_md(data)
    # Comment (10:00) comes before Review (11:00) by created_at
    assert "## Comment 1" in md
    assert "I have a question about the approach." in md
    assert "> Username: collaborator  " in md
    assert "## Review 2 [Changes requested]" in md
    assert "Please fix the typo." in md
    assert "> Username: reviewer1  " in md
    assert "> State: CHANGES_REQUESTED  " in md


def test_pr_json_to_md_empty_pr_info_defaults():
    """Empty pr_info uses N/A and defaults for number, title, dates."""
    data = {
        "pr_info": {},
        "reviews": [],
        "comments": [],
    }
    md = pr_json_to_md(data)
    assert "# #N/A No Title" in md
    assert "> Created at: N/A" in md
    assert "> Updated at: N/A" in md
