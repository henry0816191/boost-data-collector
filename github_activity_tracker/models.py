"""
Models per docs/Schema.md section 2: GitHub Activity Tracker.
References cppa_user_tracker.GitHubAccount for owner/author/assignee.
"""

from django.db import models


# --- Enums ---
class FileChangeStatus(models.TextChoices):
    ADDED = "added", "Added"
    MODIFIED = "modified", "Modified"
    REMOVED = "removed", "Removed"
    RENAMED = "renamed", "Renamed"
    COPIED = "copied", "Copied"
    CHANGED = "changed", "Changed"


class IssueState(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class IssueStateReason(models.TextChoices):
    COMPLETED = "completed", "Completed"
    NOT_PLANNED = "not_planned", "Not planned"
    REOPENED = "reopened", "Reopened"
    NULL = "null", "Null"


class PullRequestState(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    MERGED = "merged", "Merged"


# --- Part 1: Repository, Language, License ---
class Language(models.Model):
    """Reference: language name."""

    name = models.CharField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "github_activity_tracker_language"
        ordering = ["name"]


class License(models.Model):
    """Reference: license name, spdx_id, url."""

    name = models.CharField(max_length=255, unique=True, db_index=True)
    spdx_id = models.CharField(max_length=64, db_index=True, blank=True)
    url = models.URLField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "github_activity_tracker_license"
        ordering = ["name"]


class GitHubRepository(models.Model):
    """Repository metadata; owned by GitHubAccount (cppa_user_tracker)."""

    owner_account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="repositories",
        db_column="owner_account_id",
    )
    repo_name = models.CharField(max_length=255, db_index=True)
    stars = models.IntegerField(default=0)
    forks = models.IntegerField(default=0)
    description = models.TextField(blank=True)
    repo_pushed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    repo_created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    repo_updated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    licenses = models.ManyToManyField(
        License,
        related_name="repos",
        blank=True,
    )
    languages = models.ManyToManyField(
        Language,
        through="RepoLanguage",
        related_name="repos",
        blank=True,
    )

    class Meta:
        db_table = "github_activity_tracker_githubrepository"
        ordering = ["owner_account", "repo_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_account", "repo_name"],
                name="github_activity_tracker_repo_owner_name_uniq",
            )
        ]


class RepoLanguage(models.Model):
    """Repo-language link with line_count."""

    repo = models.ForeignKey(
        GitHubRepository,
        on_delete=models.CASCADE,
        related_name="repo_languages",
        db_column="repo_id",
    )
    language = models.ForeignKey(
        Language,
        on_delete=models.CASCADE,
        related_name="repo_languages",
        db_column="language_id",
    )
    line_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "github_activity_tracker_repolanguage"
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "language"],
                name="github_activity_tracker_repo_lang_uniq",
            )
        ]


# --- Part 2: Git Commit, GitHubFile, Issues ---
class GitCommit(models.Model):
    """Commit in a repo (hash, committer, comment, commit_at)."""

    id = models.BigAutoField(primary_key=True)
    repo = models.ForeignKey(
        GitHubRepository,
        on_delete=models.CASCADE,
        related_name="commits",
        db_column="repo_id",
    )
    account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="commits",
        db_column="account_id",
    )
    commit_hash = models.CharField(max_length=64, db_index=True)
    comment = models.TextField(blank=True)
    commit_at = models.DateTimeField(db_index=True)
    # Many-to-many to GitHubFile via GitCommitFileChange (status, additions, deletions, patch)
    files = models.ManyToManyField(
        "GitHubFile",
        through="GitCommitFileChange",
        related_name="commits",
        blank=True,
    )

    class Meta:
        db_table = "github_activity_tracker_gitcommit"
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "commit_hash"],
                name="github_activity_tracker_repo_commit_uniq",
            )
        ]


class GitHubFile(models.Model):
    """File in a repo (filename, repo_id, is_deleted)."""

    id = models.BigAutoField(primary_key=True)
    repo = models.ForeignKey(
        GitHubRepository,
        on_delete=models.CASCADE,
        related_name="files",
        db_column="repo_id",
    )
    filename = models.CharField(max_length=1024, db_index=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "github_activity_tracker_githubfile"
        ordering = ["repo", "filename"]


class GitCommitFileChange(models.Model):
    """Per-commit file change (links commit, GitHubFile, status, additions, deletions, patch)."""

    commit = models.ForeignKey(
        GitCommit,
        on_delete=models.CASCADE,
        related_name="file_changes",
        db_column="commit_id",
    )
    github_file = models.ForeignKey(
        GitHubFile,
        on_delete=models.CASCADE,
        related_name="commit_changes",
        db_column="github_file_id",
    )
    status = models.CharField(
        max_length=20,
        choices=FileChangeStatus.choices,
        db_index=True,
    )
    additions = models.IntegerField(default=0)
    deletions = models.IntegerField(default=0)
    patch = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "github_activity_tracker_gitcommitfilechange"
        constraints = [
            models.UniqueConstraint(
                fields=["commit", "github_file"],
                name="github_activity_tracker_commit_file_uniq",
            )
        ]


class Issue(models.Model):
    """GitHub issue (repo, creator, number, title, body, state, labels, assignees)."""

    repo = models.ForeignKey(
        GitHubRepository,
        on_delete=models.CASCADE,
        related_name="issues",
        db_column="repo_id",
    )
    account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="created_issues",
        db_column="account_id",
    )
    issue_number = models.IntegerField(db_index=True)
    issue_id = models.BigIntegerField(unique=True, db_index=True)
    title = models.CharField(max_length=1024, blank=True)
    body = models.TextField(blank=True)
    state = models.CharField(
        max_length=20,
        choices=IssueState.choices,
        db_index=True,
    )
    state_reason = models.CharField(
        max_length=20,
        choices=IssueStateReason.choices,
        blank=True,
    )
    issue_created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    issue_updated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    issue_closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    assignees = models.ManyToManyField(
        "cppa_user_tracker.GitHubAccount",
        related_name="assigned_issues",
        blank=True,
    )

    class Meta:
        db_table = "github_activity_tracker_issue"
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "issue_number"],
                name="github_activity_tracker_repo_issue_num_uniq",
            )
        ]


class IssueComment(models.Model):
    """Comment on an issue."""

    issue = models.ForeignKey(
        Issue,
        on_delete=models.CASCADE,
        related_name="comments",
        db_column="issue_id",
    )
    account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="issue_comments",
        db_column="account_id",
    )
    issue_comment_id = models.BigIntegerField(unique=True, db_index=True)
    body = models.TextField(blank=True)
    issue_comment_created_at = models.DateTimeField(null=True, blank=True)
    issue_comment_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "github_activity_tracker_issuecomment"


class IssueLabel(models.Model):
    """Issue-label name."""

    issue = models.ForeignKey(
        Issue,
        on_delete=models.CASCADE,
        related_name="labels",
        db_column="issue_id",
    )
    label_name = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "github_activity_tracker_issuelabel"
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "label_name"],
                name="github_activity_tracker_issue_label_uniq",
            )
        ]


# --- Part 3: Pull Requests ---
class PullRequest(models.Model):
    """PR (repo, creator, number, title, body, state, head_hash, base_hash, dates)."""

    repo = models.ForeignKey(
        GitHubRepository,
        on_delete=models.CASCADE,
        related_name="pull_requests",
        db_column="repo_id",
    )
    account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="created_pull_requests",
        db_column="account_id",
    )
    pr_number = models.IntegerField(db_index=True)
    pr_id = models.BigIntegerField(unique=True, db_index=True)
    title = models.CharField(max_length=1024, blank=True)
    body = models.TextField(blank=True)
    state = models.CharField(
        max_length=20,
        choices=PullRequestState.choices,
        db_index=True,
    )
    head_hash = models.CharField(max_length=64, db_index=True, blank=True)
    base_hash = models.CharField(max_length=64, db_index=True, blank=True)
    pr_created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    pr_updated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    pr_merged_at = models.DateTimeField(null=True, blank=True, db_index=True)
    pr_closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    assignees = models.ManyToManyField(
        "cppa_user_tracker.GitHubAccount",
        related_name="assigned_pull_requests",
        blank=True,
    )

    class Meta:
        db_table = "github_activity_tracker_pullrequest"
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "pr_number"],
                name="github_activity_tracker_repo_pr_num_uniq",
            )
        ]


class PullRequestReview(models.Model):
    """Review on a PR."""

    pr = models.ForeignKey(
        PullRequest,
        on_delete=models.CASCADE,
        related_name="reviews",
        db_column="pr_id",
    )
    account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="pr_reviews",
        db_column="account_id",
    )
    pr_review_id = models.BigIntegerField(unique=True, db_index=True)
    body = models.TextField(blank=True)
    in_reply_to_id = models.BigIntegerField(null=True, blank=True)
    pr_review_created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    pr_review_updated_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "github_activity_tracker_pullrequestreview"


class PullRequestComment(models.Model):
    """Comment on a PR."""

    pr = models.ForeignKey(
        PullRequest,
        on_delete=models.CASCADE,
        related_name="comments",
        db_column="pr_id",
    )
    account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="pr_comments",
        db_column="account_id",
    )
    pr_comment_id = models.BigIntegerField(unique=True, db_index=True)
    body = models.TextField(blank=True)
    pr_comment_created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    pr_comment_updated_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "github_activity_tracker_pullrequestcomment"


class PullRequestLabel(models.Model):
    """PR-label name."""

    pr = models.ForeignKey(
        PullRequest,
        on_delete=models.CASCADE,
        related_name="labels",
        db_column="pr_id",
    )
    label_name = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "github_activity_tracker_pullrequestlabel"
        constraints = [
            models.UniqueConstraint(
                fields=["pr", "label_name"],
                name="github_activity_tracker_pr_label_uniq",
            )
        ]
