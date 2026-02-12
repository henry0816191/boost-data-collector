"""
Sync Git commits with the database.

Flow:
1. Process existing JSON files in workspace/<owner>/<repo>/commits/*.json (load → DB → remove file).
2. Fetch from GitHub, save each as commits/<sha>.json, persist to DB, then remove the file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from cppa_user_tracker.services import (
    get_or_create_github_account,
    get_or_create_unknown_github_account,
)
from github_activity_tracker import fetcher, services
from github_activity_tracker.models import FileChangeStatus
from github_activity_tracker.workspace import (
    get_commit_json_path,
    iter_existing_commit_jsons,
)
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException
from github_activity_tracker.sync.utils import (
    parse_datetime,
    parse_github_user,
)

if TYPE_CHECKING:
    from github_activity_tracker.models import GitCommit, GitHubRepository

logger = logging.getLogger(__name__)

# GitHub API file status values; we store lowercase to match FileChangeStatus
_VALID_FILE_STATUSES = {c[0] for c in FileChangeStatus.choices}


def _process_commit_files(
    repo: GitHubRepository, commit_obj: GitCommit, commit_data: dict
) -> None:
    """Create/update GitHubFile and GitCommitFileChange for each file in the commit."""
    for file_info in commit_data.get("files") or []:
        filename = file_info.get("filename") or file_info.get("previous_filename")
        if not (filename and filename.strip()):
            continue
        filename = filename.strip()
        api_status = (file_info.get("status") or "modified").strip().lower()
        status = (
            api_status
            if api_status in _VALID_FILE_STATUSES
            else FileChangeStatus.CHANGED
        )
        is_deleted = status == FileChangeStatus.REMOVED
        github_file, _ = services.create_or_update_github_file(
            repo, filename, is_deleted=is_deleted
        )
        services.add_commit_file_change(
            commit_obj,
            github_file,
            status=status,
            additions=file_info.get("additions") or 0,
            deletions=file_info.get("deletions") or 0,
            patch=(file_info.get("patch") or "").strip(),
        )


def _commit_author_name_and_email(commit_data: dict) -> tuple[str, str]:
    """Get author name and email from commit blob (commit.author or commit.committer)."""
    commit = commit_data.get("commit") or {}
    author = commit.get("author") or commit.get("committer") or {}
    name = author.get("name")
    if name is None:
        name = "unknown"
    else:
        name = (name or "").strip() or "unknown"
    email = (author.get("email") or "").strip()
    return name, email


def _process_commit_data(repo: GitHubRepository, commit_data: dict) -> None:
    """Apply one commit dict to the database. Uses synthetic account (id -1, -2, ...) when no API author/committer."""
    author_dict = commit_data.get("author") or commit_data.get("committer")
    if author_dict:
        user_info = parse_github_user(author_dict)
        account, _ = get_or_create_github_account(
            github_account_id=user_info["account_id"],
            username=user_info["username"],
            display_name=user_info["display_name"],
            avatar_url=user_info["avatar_url"],
        )
    else:
        name, email = _commit_author_name_and_email(commit_data)
        account, _ = get_or_create_unknown_github_account(name=name, email=email)

    commit_hash = commit_data.get("sha")
    comment = commit_data.get("commit", {}).get("message", "")
    commit_date_str = commit_data.get("commit", {}).get("author", {}).get(
        "date"
    ) or commit_data.get("commit", {}).get("committer", {}).get("date")
    commit_at = parse_datetime(commit_date_str)

    commit_obj, _ = services.create_or_update_commit(
        repo=repo,
        account=account,
        commit_hash=commit_hash,
        comment=comment,
        commit_at=commit_at,
    )
    _process_commit_files(repo, commit_obj, commit_data)
    logger.debug("Commit %s: saved to DB", commit_hash)


def _process_existing_commit_jsons(repo: GitHubRepository) -> int:
    """Load each commits/*.json in workspace for this repo, save to DB, remove file. Returns count processed."""
    owner = repo.owner_account.username
    repo_name = repo.repo_name
    count = 0
    for path in iter_existing_commit_jsons(owner, repo_name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _process_commit_data(repo, data)
            path.unlink()
            count += 1
        except Exception as e:
            logger.exception("Failed to process %s: %s", path, e)
    return count


def sync_commits(repo: GitHubRepository) -> None:
    """1) Process existing workspace JSONs; 2) Fetch from GitHub, save as JSON, persist to DB, remove file."""
    logger.info("sync_commits: starting for repo id=%s (%s)", repo.pk, repo.repo_name)

    owner = repo.owner_account.username
    repo_name = repo.repo_name

    try:
        # Phase 1: process existing JSON files
        n_existing = _process_existing_commit_jsons(repo)
        if n_existing:
            logger.info(
                "sync_commits: processed %s existing commit JSON(s)", n_existing
            )

        # Phase 2: fetch from GitHub, write JSON, persist to DB, remove file
        client = get_github_client()
        last_commit = repo.commits.order_by("-commit_at").first()
        if last_commit:
            start_date = last_commit.commit_at + timedelta(seconds=1)
        else:
            start_date = None
        end_date = datetime.now()

        count = 0
        for commit_data in fetcher.fetch_commits_from_github(
            client, owner, repo_name, start_date, end_date
        ):
            sha = commit_data.get("sha")
            if not sha:
                continue
            json_path = get_commit_json_path(owner, repo_name, sha)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(commit_data, indent=2, default=str), encoding="utf-8"
            )
            _process_commit_data(repo, commit_data)
            json_path.unlink()
            count += 1

        logger.info(
            "sync_commits: finished for repo id=%s; %s existing + %s fetched",
            repo.pk,
            n_existing,
            count,
        )

    except (RateLimitException, ConnectionException) as e:
        logger.error("sync_commits: failed for repo id=%s: %s", repo.pk, e)
        raise
    except Exception as e:
        logger.exception(
            "sync_commits: unexpected error for repo id=%s: %s", repo.pk, e
        )
        raise
