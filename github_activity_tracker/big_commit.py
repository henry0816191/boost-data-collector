"""
Handle commits with 300+ file changes (GitHub API limit).

Flow:
1. Detect when commit has 300 files (possibly truncated).
2. Clone repo and use git to get full file list.
3. Build commit payload with full files array for sync.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

from github_ops import clone_repo, get_commit_file_changes
from github_activity_tracker.workspace import (
    get_clone_dir,
    register_clone,
    remove_clone_dir,
)

logger = logging.getLogger(__name__)

# Per-repo locks to prevent concurrent clone/fetch for same repo
_repo_locks: dict[tuple[str, str], threading.Lock] = {}
_repo_locks_lock = threading.Lock()


def _get_repo_lock(owner: str, repo: str) -> threading.Lock:
    """Get or create a lock for a specific repo."""
    key = (owner, repo)
    with _repo_locks_lock:
        if key not in _repo_locks:
            _repo_locks[key] = threading.Lock()
        return _repo_locks[key]


def is_commit_truncated(commit_data: dict) -> bool:
    """
    Check if commit files array is possibly truncated (exactly 300 files).

    Returns True if commit has exactly 300 files (GitHub API limit).
    """
    files = commit_data.get("files") or []
    return len(files) == 300


def ensure_repo_cloned(owner: str, repo: str) -> Path:
    """
    Ensure repo is cloned in workspace; clone or fetch as needed.

    Returns path to cloned repo.
    Registers clone path for cleanup when run finishes.
    Thread-safe (uses per-repo lock).
    """
    clone_path = get_clone_dir(owner, repo)
    lock = _get_repo_lock(owner, repo)

    with lock:
        if clone_path.exists() and (clone_path / ".git").is_dir():
            # Already cloned; fetch updates
            logger.info(
                "Repo %s/%s already cloned at %s, fetching updates",
                owner,
                repo,
                clone_path,
            )
            try:
                subprocess.run(
                    ["git", "-C", str(clone_path), "fetch", "--all"],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=300,
                )
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as e:
                logger.warning("Failed to fetch updates for %s/%s: %s", owner, repo, e)
                # Continue with existing clone
        else:
            # Clone repo (remove existing dir if present, so git clone does not fail with exit 128)
            if clone_path.exists():
                logger.warning(
                    "Removing existing non-git directory %s before clone",
                    clone_path,
                )
                if not remove_clone_dir(clone_path):
                    raise OSError(
                        "Could not remove existing directory %s (e.g. file in use)"
                        % clone_path
                    )
            logger.info("Cloning %s/%s to %s", owner, repo, clone_path)
            clone_repo(f"{owner}/{repo}", clone_path)

        # Register for cleanup
        register_clone(clone_path)

    return clone_path


# Git's empty tree SHA (same in every repo). Used to diff initial commits.
# https://github.com/git/git/blob/master/cache.h
_GIT_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def get_full_commit_files(
    owner: str,
    repo: str,
    commit_sha: str,
    parent_shas: list[str] | None = None,
) -> list[dict]:
    """
    Get full list of changed files for a commit via git (for commits with 300+ files).

    1. Ensures repo is cloned.
    2. Calls github_ops.get_commit_file_changes to get full file list.
    3. For initial commits (no parent), diffs against git's empty tree so we still get full file list + patches.

    Returns list of file dicts matching GitHub API shape.
    Raises exception if clone or git operations fail.
    """
    # Ensure clone (once)
    clone_path = ensure_repo_cloned(owner, repo)

    if parent_shas is None:
        # Resolve parents using git log if not provided
        result = subprocess.run(
            ["git", "-C", str(clone_path), "log", "--pretty=%P", "-n", "1", commit_sha],
            capture_output=True,
            text=True,
            check=True,
        )
        parent_shas = result.stdout.strip().split()

    # For initial commit, diff against empty tree to get all files as "added" with full patches
    is_initial_commit = len(parent_shas) == 0
    parent_sha = parent_shas[0] if parent_shas else _GIT_EMPTY_TREE_SHA
    if is_initial_commit:
        logger.debug(
            "Commit %s is initial commit, diffing against empty tree",
            commit_sha[:7],
        )

    # Get full file list via github_ops
    logger.info("Getting full file list for commit %s via git", commit_sha[:7])
    try:
        files = get_commit_file_changes(clone_path, parent_sha, commit_sha)
    except Exception as e:
        logger.error(
            "Commit %s: git diff failed (%s), re-raising",
            commit_sha[:7],
            e,
        )
        raise RuntimeError(
            "Commit %s: could not get full file list via git (git diff failed: %s)"
            % (commit_sha[:7], e)
        ) from e
    return files
