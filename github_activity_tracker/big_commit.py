"""
Handle commits with 300+ file changes (GitHub API limit).

Flow:
1. Detect when commit has 300 files (possibly truncated).
2. Optionally check real count via GitHub Trees API.
3. If > 300, clone repo and use git to get full file list.
4. Build commit payload with full files array for sync.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from github_ops import clone_repo, get_commit_file_changes
from github_activity_tracker.workspace import get_clone_dir, register_clone

if TYPE_CHECKING:
    from github_ops.client import GitHubAPIClient

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


def get_changed_file_count_via_trees(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    commit_data: dict,
) -> Optional[int]:
    """
    Get real changed file count via GitHub Trees API (compare commit tree vs parent tree).

    Returns count, or None if trees are truncated or error occurs.

    Note: This is optional; can skip and just use clone path for all 300-file commits.
    """
    try:
        # Get commit tree SHA and parent SHA
        commit_tree_sha = commit_data.get("commit", {}).get("tree", {}).get("sha")
        parents = commit_data.get("parents") or []
        if not parents:
            logger.debug("Commit has no parent (initial commit), skipping tree check")
            return None
        parent_sha = parents[0].get("sha")

        if not commit_tree_sha or not parent_sha:
            logger.warning("Missing tree or parent SHA, cannot check via trees API")
            return None

        # Get parent commit to get its tree SHA
        parent_commit = client.rest_request(
            f"/repos/{owner}/{repo}/commits/{parent_sha}"
        )
        if not parent_commit:
            logger.warning("Could not fetch parent commit %s", parent_sha)
            return None
        parent_tree_sha = parent_commit.get("commit", {}).get("tree", {}).get("sha")

        if not parent_tree_sha:
            logger.warning("Could not get parent tree SHA")
            return None

        # Fetch both trees (recursive)
        commit_tree = client.rest_request(
            f"/repos/{owner}/{repo}/git/trees/{commit_tree_sha}?recursive=1"
        )
        parent_tree = client.rest_request(
            f"/repos/{owner}/{repo}/git/trees/{parent_tree_sha}?recursive=1"
        )

        if not commit_tree or not parent_tree:
            logger.warning("Could not fetch trees")
            return None

        # Check if truncated
        if commit_tree.get("truncated") or parent_tree.get("truncated"):
            logger.info("Trees are truncated, cannot get accurate count via API")
            return None

        # Get blob paths (type == "blob" means file)
        commit_blobs = {
            item["path"]: item["sha"]
            for item in commit_tree.get("tree", [])
            if item.get("type") == "blob"
        }
        parent_blobs = {
            item["path"]: item["sha"]
            for item in parent_tree.get("tree", [])
            if item.get("type") == "blob"
        }

        # Count changed files (added, removed, or modified)
        added = set(commit_blobs.keys()) - set(parent_blobs.keys())
        removed = set(parent_blobs.keys()) - set(commit_blobs.keys())
        modified = {
            path
            for path in commit_blobs
            if path in parent_blobs and commit_blobs[path] != parent_blobs[path]
        }

        total_changed = len(added) + len(removed) + len(modified)
        logger.info(
            "Trees API: %d added, %d removed, %d modified = %d total changed",
            len(added),
            len(removed),
            len(modified),
            total_changed,
        )
        return total_changed

    except Exception as e:
        logger.warning("Failed to get changed file count via trees: %s", e)
        return None


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
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logger.warning("Failed to fetch updates for %s/%s: %s", owner, repo, e)
                # Continue with existing clone
        else:
            # Clone repo (remove existing dir if present, so git clone does not fail with exit 128)
            if clone_path.exists():
                logger.warning(
                    "Removing existing non-git directory %s before clone", clone_path
                )
                shutil.rmtree(clone_path)
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
    commit_data: dict,
) -> list[dict]:
    """
    Get full list of changed files for a commit via git (for commits with 300+ files).

    1. Ensures repo is cloned.
    2. Calls github_ops.get_commit_file_changes to get full file list.
    3. For initial commits (no parent), diffs against git's empty tree so we still get full file list + patches.

    Returns list of file dicts matching GitHub API shape.
    Raises exception if clone or git operations fail.
    """
    commit_sha = commit_data.get("sha")
    parents = commit_data.get("parents") or []

    # For initial commit, diff against empty tree to get all files as "added" with full patches
    is_initial_commit = not parents
    parent_sha = parents[0].get("sha") if parents else _GIT_EMPTY_TREE_SHA
    if is_initial_commit:
        logger.info(
            "Commit %s is initial commit, diffing against empty tree",
            commit_sha[:7],
        )

    # Ensure clone
    clone_path = ensure_repo_cloned(owner, repo)

    # Get full file list via github_ops
    logger.info("Getting full file list for commit %s via git", commit_sha[:7])
    try:
        files = get_commit_file_changes(clone_path, parent_sha, commit_sha)
    except Exception as e:
        if is_initial_commit:
            # Fallback: e.g. empty tree not in shallow clone
            logger.warning(
                "Initial commit %s: git diff failed (%s), using API files",
                commit_sha[:7],
                e,
            )
            files = commit_data.get("files") or []
        else:
            raise
    return files
