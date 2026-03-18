"""
Sync Git commits with the database.

Flow:
1. Process existing JSON files in workspace/<owner>/<repo>/commits/*.json (load → DB → remove file).
2. Fetch from GitHub, save each as commits/<sha>.json, persist to DB, then remove the file.
3. For commits with 300+ files (truncated), submit background task to clone repo and get full list via git.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from cppa_user_tracker.services import (
    get_or_create_github_account,
    get_or_create_unknown_github_account,
)
from github_activity_tracker import big_commit, fetcher, services
from github_activity_tracker.models import FileChangeStatus
from github_activity_tracker.workspace import (
    get_commit_json_path,
    iter_existing_commit_jsons,
)
from github_ops import get_github_client
from github_ops.client import ConnectionException, RateLimitException
from .raw_source import save_commit_raw_source
from .etag_cache import RedisListETagCache
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
    repo: GitHubRepository, commit_obj: GitCommit, files: list[dict]
) -> None:
    """Create/update GitHubFile and GitCommitFileChange for each file in the commit."""
    for file_info in files:
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

        # Handle rename: link new filename to old filename
        previous_filename = file_info.get("previous_filename")
        if status == FileChangeStatus.RENAMED and previous_filename:
            previous_filename = previous_filename.strip()
            old_file, _ = services.create_or_update_github_file(
                repo, previous_filename, is_deleted=False
            )
            github_file, _ = services.create_or_update_github_file(
                repo, filename, is_deleted=is_deleted
            )
            # Link new file to old file
            if github_file.previous_filename_id != old_file.id:
                services.set_github_file_previous_filename(github_file, old_file)
        else:
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
    files = commit_data.get("files") or []
    if files:
        _process_commit_files(repo, commit_obj, files)
    else:
        logger.warning("Commit %s has no files", commit_hash)
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
            save_commit_raw_source(owner, repo_name, data)
            path.unlink()
            count += 1
        except Exception as e:
            logger.exception("Failed to process %s: %s", path, e)
    return count


def _process_big_commit_worker(owner: str, repo_name: str, commit_data: dict) -> None:
    """
    Background worker: get full file list for big commit (300+ files) via git clone.

    1. Clone repo (or fetch if already cloned).
    2. Get full file list via git.
    3. Write full commit JSON to workspace for later sync.

    Does NOT call _process_commit_data (to avoid DB access from worker thread).
    """
    try:
        sha = commit_data.get("sha")
        logger.info(
            "Processing big commit %s/%s:%s in background",
            owner,
            repo_name,
            sha[:7],
        )

        # Get full file list via git
        parents = commit_data.get("parents") or []
        parent_shas = [p.get("sha") for p in parents if p.get("sha")]
        try:
            full_files = big_commit.get_full_commit_files(
                owner, repo_name, commit_sha=sha, parent_shas=parent_shas
            )
        except Exception as e:
            logger.exception(
                "Failed to get full file list for big commit %s/%s:%s: %s",
                owner,
                repo_name,
                sha[:7],
                e,
            )
            full_files = commit_data.get("files") or []

        # Build new commit_data with full files
        full_commit_data = commit_data.copy()
        full_commit_data["files"] = full_files

        # Write JSON to workspace (sync will pick it up in second pass)
        json_path = get_commit_json_path(owner, repo_name, sha)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(full_commit_data, indent=2, default=str),
            encoding="utf-8",
        )

        logger.info(
            "Big commit %s/%s:%s processed: %d files written to %s",
            owner,
            repo_name,
            sha[:7],
            len(full_files),
            json_path,
        )
    except Exception as e:
        logger.exception(
            "Failed to process big commit %s/%s:%s: %s",
            owner,
            repo_name,
            commit_data.get("sha", "unknown")[:7],
            e,
        )
        # Write original commit data (with 300 files) so we don't lose the commit
        try:
            json_path = get_commit_json_path(owner, repo_name, commit_data.get("sha"))
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(commit_data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.warning(
                "Wrote partial commit data (300 files) for %s after error",
                commit_data.get("sha")[:7],
            )
        except Exception as write_error:
            logger.error("Failed to write fallback commit JSON: %s", write_error)


def sync_commits(
    repo: GitHubRepository,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> None:
    """Sync commits for a repo.

    1) Process existing workspace JSONs.
    2) Fetch from GitHub; for normal commits, persist immediately.
    3) For big commits (300+ files), submit background task to get full list via git.
    4) Wait for all background tasks.
    5) Process big commit JSONs (written by workers) in second pass.

    Args:
        repo: Repository to sync.
        start_date: Override start date (default: last commit date + 1s, or None if no commits).
        end_date: Override end date (default: None = no end; fetcher uses stable cache key).
    """
    logger.info("sync_commits: starting for repo id=%s (%s)", repo.pk, repo.repo_name)

    owner = repo.owner_account.username
    repo_name = repo.repo_name

    try:
        # Phase 1: process existing JSON files (from previous runs or workers)
        n_existing = _process_existing_commit_jsons(repo)
        if n_existing:
            logger.info(
                "sync_commits: processed %s existing commit JSON(s)",
                n_existing,
            )

        # Phase 2: fetch from GitHub
        client = get_github_client()
        if start_date is None:
            last_commit = repo.commits.order_by("-commit_at").first()
            if last_commit:
                start_date = last_commit.commit_at + timedelta(seconds=1)
        # Leave end_date as None when not set so the fetcher uses until_iso=""
        # and the ETag cache key stays stable across runs (no end = stable key).

        # Create thread pool for big commits (max 2-4 workers to avoid heavy disk/network load)
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="big_commit")
        futures = []

        count_normal = 0
        count_big = 0

        try:
            etag_cache = RedisListETagCache(repo_id=repo.pk)
            for commit_data in fetcher.fetch_commits_from_github(
                client, owner, repo_name, start_date, end_date, etag_cache=etag_cache
            ):
                sha = commit_data.get("sha")
                if not sha:
                    continue

                # Check if commit is truncated (300 files = possible truncation)
                is_truncated = big_commit.is_commit_truncated(commit_data)

                if is_truncated:
                    # Big commit: submit to background worker
                    logger.info(
                        "Commit %s has 300 files (possibly truncated), submitting to background",
                        sha[:7],
                    )
                    future = executor.submit(
                        _process_big_commit_worker,
                        owner,
                        repo_name,
                        commit_data,
                    )
                    futures.append(future)
                    count_big += 1
                else:
                    # Normal commit: process immediately
                    json_path = get_commit_json_path(owner, repo_name, sha)
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                    json_path.write_text(
                        json.dumps(commit_data, indent=2, default=str),
                        encoding="utf-8",
                    )
                    _process_commit_data(repo, commit_data)
                    json_path.unlink()
                    count_normal += 1

            # Phase 3: wait for all big commit tasks to finish
            if futures:
                logger.info("Waiting for %d big commit task(s) to finish", len(futures))
                executor.shutdown(wait=True)

                # Check for exceptions in tasks
                for i, future in enumerate(futures):
                    try:
                        future.result()  # Will raise if task raised
                    except Exception as e:
                        logger.error("Big commit task %d raised exception: %s", i, e)

                # Phase 4: process big commit JSONs (written by workers)
                logger.info("Processing big commit JSONs written by workers")
                n_big_processed = _process_existing_commit_jsons(repo)
                logger.info(
                    "Processed %d big commit JSON(s) from workers",
                    n_big_processed,
                )
            else:
                executor.shutdown(wait=False)

        finally:
            # Ensure executor is shut down even if exception occurs
            executor.shutdown(wait=True)

        logger.info(
            "sync_commits: finished for repo id=%s; %s existing + %s normal + %s big commits",
            repo.pk,
            n_existing,
            count_normal,
            count_big,
        )

    except (RateLimitException, ConnectionException) as e:
        logger.error("sync_commits: failed for repo id=%s: %s", repo.pk, e)
        raise
    except Exception as e:
        logger.exception(
            "sync_commits: unexpected error for repo id=%s: %s", repo.pk, e
        )
        raise
