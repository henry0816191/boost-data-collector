"""Database models for clang_github_tracker (no FKs to other apps)."""

from __future__ import annotations

from django.db import models


class ClangGithubIssueItem(models.Model):
    """One row per GitHub issue or PR number for the configured llvm repo."""

    number = models.PositiveIntegerField(unique=True)
    is_pull_request = models.BooleanField(default=False)
    github_created_at = models.DateTimeField(null=True, blank=True)
    github_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="GitHub API updated_at; drives fetch watermarks.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(
        auto_now=True,
        db_index=True,
        help_text="Last DB save; drives Pinecone incrementality vs final_sync_at.",
    )

    class Meta:
        """Maps to ``clang_github_tracker_issue_item``."""

        db_table = "clang_github_tracker_issue_item"


class ClangGithubCommit(models.Model):
    """One row per commit SHA synced for the configured llvm repo."""

    sha = models.CharField(max_length=40, unique=True)
    github_committed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Maps to ``clang_github_tracker_commit``."""

        db_table = "clang_github_tracker_commit"
