"""
Service layer for github_activity_tracker.

All creates/updates/deletes for this app's models must go through functions in this
module. Do not call Model.objects.create(), model.save(), or model.delete() from
outside this module (e.g. from management commands, views, or other apps).

See docs/Contributing.md for the project-wide rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datetime import datetime
from typing import Optional

from .models import (
    CreatedReposByLanguage,
    GitCommit,
    GitCommitFileChange,
    GitHubFile,
    GitHubRepository,
    Issue,
    IssueComment,
    IssueLabel,
    IssueState,
    Language,
    License,
    PullRequest,
    PullRequestComment,
    PullRequestLabel,
    PullRequestReview,
    PullRequestState,
    RepoLanguage,
)

if TYPE_CHECKING:
    from .models import Issue, PullRequest
    from cppa_user_tracker.models import GitHubAccount


# --- Language ---
def get_or_create_language(name: str) -> tuple[Language, bool]:
    """Get or create a Language by name. Returns (Language, created).

    Raises:
        ValueError: If name is empty or whitespace-only.
    """
    if not (name and name.strip()):
        raise ValueError("Language name must not be empty.")
    return Language.objects.get_or_create(name=name.strip())


def create_or_update_created_repos_by_language(
    language: Language,
    year: int,
    all_repos: int,
    significant_repos: int,
) -> tuple[CreatedReposByLanguage, bool]:
    """Create or update CreatedReposByLanguage for (language, year)."""
    row, created = CreatedReposByLanguage.objects.get_or_create(
        language=language,
        year=year,
        defaults={
            "all_repos": all_repos,
            "significant_repos": significant_repos,
        },
    )
    if not created:
        update_fields: list[str] = []
        if row.all_repos != all_repos:
            row.all_repos = all_repos
            update_fields.append("all_repos")
        if row.significant_repos != significant_repos:
            row.significant_repos = significant_repos
            update_fields.append("significant_repos")
        if update_fields:
            row.save(update_fields=update_fields + ["updated_at"])
    return row, created


# --- License ---
def get_or_create_license(
    name: str,
    spdx_id: str = "",
    url: str = "",
) -> tuple[License, bool]:
    """Get or create a License by name. If exists, updates spdx_id and url. Returns (License, created).

    Raises:
        ValueError: If name is empty or whitespace-only.
    """
    if not (name and name.strip()):
        raise ValueError("License name must not be empty.")
    license_obj, created = License.objects.get_or_create(
        name=name.strip(),
        defaults={"spdx_id": spdx_id, "url": url},
    )
    if not created:
        license_obj.spdx_id = spdx_id
        license_obj.url = url
        license_obj.save(update_fields=["spdx_id", "url"])
    return license_obj, created


# --- GitHubRepository ---
def get_or_create_repository(
    owner_account: GitHubAccount,
    repo_name: str,
    **defaults: Any,
) -> tuple[GitHubRepository, bool]:
    """Get or create a GitHubRepository by owner_account and repo_name. If exists, updates fields in defaults. Returns (repo, created)."""
    updatable = {
        "stars",
        "forks",
        "description",
        "repo_pushed_at",
        "repo_created_at",
        "repo_updated_at",
    }
    repo, created = GitHubRepository.objects.get_or_create(
        owner_account=owner_account,
        repo_name=repo_name,
        defaults=defaults,
    )
    if not created and defaults:
        update_fields = []
        for key in updatable:
            if key in defaults and getattr(repo, key) != defaults[key]:
                setattr(repo, key, defaults[key])
                update_fields.append(key)
        if update_fields:
            repo.save(update_fields=update_fields)
    return repo, created


def ensure_repository_owner(
    repo: GitHubRepository, owner_account: GitHubAccount
) -> None:
    """Ensure repo has owner_account set (fixes rows with null owner_account_id)."""
    repo.refresh_from_db()
    if repo.owner_account_id is None:
        repo.owner_account = owner_account
        repo.save(update_fields=["owner_account_id"])


def add_repo_license(repo: GitHubRepository, license_obj: License) -> None:
    """Add a License to a repo (M2M). Idempotent."""
    repo.licenses.add(license_obj)


def remove_repo_license(repo: GitHubRepository, license_obj: License) -> None:
    """Remove a License from a repo."""
    repo.licenses.remove(license_obj)


# --- RepoLanguage (through model) ---
def add_repo_language(
    repo: GitHubRepository,
    language: Language,
    line_count: int = 0,
) -> tuple[RepoLanguage, bool]:
    """Add or update a repo–language link with line_count. If exists, updates line_count. Returns (RepoLanguage, created)."""
    rl, created = RepoLanguage.objects.get_or_create(
        repo=repo,
        language=language,
        defaults={"line_count": line_count},
    )
    if not created and rl.line_count != line_count:
        rl.line_count = line_count
        rl.save(update_fields=["line_count"])
    return rl, created


def update_repo_language_line_count(
    repo: GitHubRepository,
    language: Language,
    line_count: int,
) -> RepoLanguage:
    """Update line_count for an existing repo–language link."""
    rl = RepoLanguage.objects.get(repo=repo, language=language)
    rl.line_count = line_count
    rl.save()
    return rl


# --- GitCommit, GitHubFile, GitCommitFileChange ---


def create_or_update_commit(
    repo: GitHubRepository,
    account: GitHubAccount,
    commit_hash: str,
    comment: str = "",
    commit_at: Optional[datetime] = None,
) -> tuple[GitCommit, bool]:
    """Create or update a GitCommit by repo + commit_hash. Returns (commit, created)."""
    from datetime import datetime, timezone

    if not commit_at:
        commit_at = datetime.now(timezone.utc)
    comment_val = comment or ""

    commit_obj, created = GitCommit.objects.get_or_create(
        repo=repo,
        commit_hash=commit_hash,
        defaults={
            "account": account,
            "comment": comment_val,
            "commit_at": commit_at,
        },
    )
    if not created:
        commit_obj.account = account
        commit_obj.comment = comment_val
        commit_obj.commit_at = commit_at
        commit_obj.save()
    return commit_obj, created


def create_or_update_github_file(
    repo: GitHubRepository,
    filename: str,
    is_deleted: bool = False,
) -> tuple[GitHubFile, bool]:
    """Create or update a GitHubFile by repo + filename. Returns (file, created)."""
    # PostgreSQL TEXT cannot contain NUL (0x00)
    filename = (filename or "").replace("\x00", "")
    github_file, created = GitHubFile.objects.get_or_create(
        repo=repo,
        filename=filename,
        defaults={"is_deleted": is_deleted},
    )
    if not created:
        github_file.is_deleted = is_deleted
        github_file.save()
    return github_file, created


def add_commit_file_change(
    commit: GitCommit,
    github_file: GitHubFile,
    status: str,
    additions: int = 0,
    deletions: int = 0,
    patch: str = "",
) -> tuple[GitCommitFileChange, bool]:
    """Add or update a file change for a commit. If exists, updates status, additions, deletions, patch. Returns (file_change, created)."""
    # PostgreSQL TEXT cannot contain NUL (0x00); strip from patch (e.g. from git diff of binary files)
    patch_val = (patch or "").replace("\x00", "")
    obj, created = GitCommitFileChange.objects.get_or_create(
        commit=commit,
        github_file=github_file,
        defaults={
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "patch": patch_val,
        },
    )
    if not created:
        obj.status = status
        obj.additions = additions
        obj.deletions = deletions
        obj.patch = patch_val
        obj.save(update_fields=["status", "additions", "deletions", "patch"])
    return obj, created


# --- Issue ---
def add_issue_assignee(issue: Issue, account: GitHubAccount) -> None:
    """Add an assignee to an issue (M2M). Idempotent."""
    issue.assignees.add(account)


def remove_issue_assignee(issue: Issue, account: GitHubAccount) -> None:
    """Remove an assignee from an issue."""
    issue.assignees.remove(account)


# --- IssueLabel ---
def add_issue_label(issue: Issue, label_name: str) -> tuple[IssueLabel, bool]:
    """Add a label to an issue. Returns (IssueLabel, created)."""
    label_name_val = label_name or ""
    return IssueLabel.objects.get_or_create(
        issue=issue,
        label_name=label_name_val,
    )


def remove_issue_label(issue: Issue, label_name: str) -> None:
    """Remove a label from an issue."""
    IssueLabel.objects.filter(issue=issue, label_name=label_name).delete()


# --- PullRequest ---
def add_pr_assignee(pr: PullRequest, account: GitHubAccount) -> None:
    """Add an assignee to a PR (M2M). Idempotent."""
    pr.assignees.add(account)


def remove_pr_assignee(pr: PullRequest, account: GitHubAccount) -> None:
    """Remove an assignee from a PR."""
    pr.assignees.remove(account)


# --- PullRequestLabel ---
def add_pull_request_label(
    pr: PullRequest, label_name: str
) -> tuple[PullRequestLabel, bool]:
    """Add a label to a pull request. Returns (PullRequestLabel, created)."""
    label_name_val = label_name or ""
    return PullRequestLabel.objects.get_or_create(
        pr=pr,
        label_name=label_name_val,
    )


def remove_pull_request_label(pr: PullRequest, label_name: str) -> None:
    """Remove a label from a pull request."""
    PullRequestLabel.objects.filter(pr=pr, label_name=label_name).delete()


# --- Issue (create/update) ---
def create_or_update_issue(
    repo: GitHubRepository,
    account: GitHubAccount,
    issue_number: int,
    issue_id: int,
    title: str = "",
    body: str = "",
    state: str = IssueState.OPEN,
    state_reason: str = "",
    issue_created_at: Optional[datetime] = None,
    issue_updated_at: Optional[datetime] = None,
    issue_closed_at: Optional[datetime] = None,
) -> tuple[Issue, bool]:
    """Create or update an Issue by issue_id. Returns (issue, created)."""
    # GitHub API can return null for title/body/state_reason; store as empty string.
    title_val = title or ""
    body_val = body or ""
    state_reason_val = state_reason or ""
    issue_obj, created = Issue.objects.get_or_create(
        issue_id=issue_id,
        defaults={
            "repo": repo,
            "account": account,
            "issue_number": issue_number,
            "title": title_val,
            "body": body_val,
            "state": state,
            "state_reason": state_reason_val,
            "issue_created_at": issue_created_at,
            "issue_updated_at": issue_updated_at,
            "issue_closed_at": issue_closed_at,
        },
    )
    if not created:
        issue_obj.repo = repo
        issue_obj.account = account
        issue_obj.issue_number = issue_number
        issue_obj.title = title_val
        issue_obj.body = body_val
        issue_obj.state = state
        issue_obj.state_reason = state_reason_val
        issue_obj.issue_created_at = issue_created_at
        issue_obj.issue_updated_at = issue_updated_at
        issue_obj.issue_closed_at = issue_closed_at
        issue_obj.save()
    return issue_obj, created


# --- IssueComment ---
def create_or_update_issue_comment(
    issue: Issue,
    account: GitHubAccount,
    issue_comment_id: int,
    body: str = "",
    issue_comment_created_at: Optional[datetime] = None,
    issue_comment_updated_at: Optional[datetime] = None,
) -> tuple[IssueComment, bool]:
    """Create or update an IssueComment by issue_comment_id. Returns (comment, created)."""
    body_val = body or ""
    comment_obj, created = IssueComment.objects.get_or_create(
        issue_comment_id=issue_comment_id,
        defaults={
            "issue": issue,
            "account": account,
            "body": body_val,
            "issue_comment_created_at": issue_comment_created_at,
            "issue_comment_updated_at": issue_comment_updated_at,
        },
    )
    if not created:
        comment_obj.issue = issue
        comment_obj.account = account
        comment_obj.body = body_val
        comment_obj.issue_comment_created_at = issue_comment_created_at
        comment_obj.issue_comment_updated_at = issue_comment_updated_at
        comment_obj.save()
    return comment_obj, created


# --- PullRequest (create/update) ---
def create_or_update_pull_request(
    repo: GitHubRepository,
    account: GitHubAccount,
    pr_number: int,
    pr_id: int,
    title: str = "",
    body: str = "",
    state: str = PullRequestState.OPEN,
    head_hash: str = "",
    base_hash: str = "",
    pr_created_at: Optional[datetime] = None,
    pr_updated_at: Optional[datetime] = None,
    pr_merged_at: Optional[datetime] = None,
    pr_closed_at: Optional[datetime] = None,
) -> tuple[PullRequest, bool]:
    """Create or update a PullRequest by pr_id. Returns (pr, created)."""
    # GitHub API can return null for title/body/head/base; store as empty string.
    title_val = title or ""
    body_val = body or ""
    head_hash_val = head_hash or ""
    base_hash_val = base_hash or ""
    pr_obj, created = PullRequest.objects.get_or_create(
        pr_id=pr_id,
        defaults={
            "repo": repo,
            "account": account,
            "pr_number": pr_number,
            "title": title_val,
            "body": body_val,
            "state": state,
            "head_hash": head_hash_val,
            "base_hash": base_hash_val,
            "pr_created_at": pr_created_at,
            "pr_updated_at": pr_updated_at,
            "pr_merged_at": pr_merged_at,
            "pr_closed_at": pr_closed_at,
        },
    )
    if not created:
        pr_obj.repo = repo
        pr_obj.account = account
        pr_obj.pr_number = pr_number
        pr_obj.title = title_val
        pr_obj.body = body_val
        pr_obj.state = state
        pr_obj.head_hash = head_hash_val
        pr_obj.base_hash = base_hash_val
        pr_obj.pr_created_at = pr_created_at
        pr_obj.pr_updated_at = pr_updated_at
        pr_obj.pr_merged_at = pr_merged_at
        pr_obj.pr_closed_at = pr_closed_at
        pr_obj.save()
    return pr_obj, created


# --- PullRequestComment ---
def create_or_update_pr_comment(
    pr: PullRequest,
    account: GitHubAccount,
    pr_comment_id: int,
    body: str = "",
    pr_comment_created_at: Optional[datetime] = None,
    pr_comment_updated_at: Optional[datetime] = None,
) -> tuple[PullRequestComment, bool]:
    """Create or update a PullRequestComment by pr_comment_id. Returns (comment, created)."""
    body_val = body or ""
    comment_obj, created = PullRequestComment.objects.get_or_create(
        pr_comment_id=pr_comment_id,
        defaults={
            "pr": pr,
            "account": account,
            "body": body_val,
            "pr_comment_created_at": pr_comment_created_at,
            "pr_comment_updated_at": pr_comment_updated_at,
        },
    )
    if not created:
        comment_obj.pr = pr
        comment_obj.account = account
        comment_obj.body = body_val
        comment_obj.pr_comment_created_at = pr_comment_created_at
        comment_obj.pr_comment_updated_at = pr_comment_updated_at
        comment_obj.save()
    return comment_obj, created


# --- PullRequestReview ---
def create_or_update_pr_review(
    pr: PullRequest,
    account: GitHubAccount,
    pr_review_id: int,
    body: str = "",
    in_reply_to_id: Optional[int] = None,
    pr_review_created_at: Optional[datetime] = None,
    pr_review_updated_at: Optional[datetime] = None,
) -> tuple[PullRequestReview, bool]:
    """Create or update a PullRequestReview by pr_review_id. Returns (review, created)."""
    body_val = body or ""
    review_obj, created = PullRequestReview.objects.get_or_create(
        pr_review_id=pr_review_id,
        defaults={
            "pr": pr,
            "account": account,
            "body": body_val,
            "in_reply_to_id": in_reply_to_id,
            "pr_review_created_at": pr_review_created_at,
            "pr_review_updated_at": pr_review_updated_at,
        },
    )
    if not created:
        review_obj.pr = pr
        review_obj.account = account
        review_obj.body = body_val
        review_obj.in_reply_to_id = in_reply_to_id
        review_obj.pr_review_created_at = pr_review_created_at
        review_obj.pr_review_updated_at = pr_review_updated_at
        review_obj.save()
    return review_obj, created
