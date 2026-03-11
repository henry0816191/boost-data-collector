"""
Git and content operations for GitHub: clone, push, fetch one file, upload file.
All apps use this module (and github_ops.client) for GitHub operations.
"""

from __future__ import annotations

import base64
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_client, get_github_token

logger = logging.getLogger(__name__)

# Timeout (seconds) for top-level git diff subprocess calls (--name-status, --numstat)
GIT_DIFF_TIMEOUT = 60
# Timeout (seconds) for git clone and push (network I/O)
GIT_CMD_TIMEOUT_SECONDS = 300


def _url_with_token(url: str, token: str) -> str:
    """Inject token into GitHub HTTPS URL for auth."""
    if not token:
        return url
    return re.sub(
        r"^(https://)(github\.com/)",
        r"\1" + token + r"@\2",
        url,
        count=1,
    )


def clone_repo(
    url_or_slug: str,
    dest_dir: str | Path,
    *,
    token: Optional[str] = None,
    depth: Optional[int] = None,
) -> None:
    """
    Clone a GitHub repo. Uses scraping token by default (read-only).
    """
    dest_dir = Path(dest_dir)
    if token is None:
        token = get_github_token(use="scraping")
    if "github.com" not in url_or_slug and "/" in url_or_slug:
        url_or_slug = f"https://github.com/{url_or_slug}"
    clone_url = _url_with_token(
        (
            url_or_slug
            if url_or_slug.endswith(".git")
            else url_or_slug.rstrip("/") + ".git"
        ),
        token,
    )
    cmd = ["git", "clone", clone_url, str(dest_dir)]
    if depth is not None:
        cmd.extend(["--depth", str(depth)])
    logger.info("Cloning %s -> %s", url_or_slug, dest_dir)
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_CMD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "git clone timed out after %ss (%s -> %s)",
            GIT_CMD_TIMEOUT_SECONDS,
            url_or_slug,
            dest_dir,
        )
        raise
    except subprocess.CalledProcessError as e:
        logger.warning(
            "git clone failed (%s -> %s), returncode=%s",
            url_or_slug,
            dest_dir,
            e.returncode,
        )
        raise


def push(
    repo_dir: str | Path,
    remote: str = "origin",
    branch: Optional[str] = None,
    *,
    token: Optional[str] = None,
) -> None:
    """
    Push to remote. Uses push token by default.
    """
    repo_dir = Path(repo_dir)
    if token is None:
        token = get_github_token(use="push")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "get-url", remote],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=GIT_CMD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "git remote get-url timed out after %ss (%s)",
            GIT_CMD_TIMEOUT_SECONDS,
            repo_dir,
        )
        raise
    except subprocess.CalledProcessError as e:
        logger.warning(
            "git remote get-url failed (%s), returncode=%s", repo_dir, e.returncode
        )
        raise
    remote_url = result.stdout.strip()
    push_url = _url_with_token(remote_url, token)
    cmd = ["git", "-C", str(repo_dir), "push", push_url]
    if branch:
        cmd.append(branch)
    logger.info("Pushing %s %s", repo_dir, branch or "(current)")
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_CMD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "git push timed out after %ss (%s)",
            GIT_CMD_TIMEOUT_SECONDS,
            repo_dir,
        )
        raise
    except subprocess.CalledProcessError as e:
        logger.warning("git push failed (%s), returncode=%s", repo_dir, e.returncode)
        raise


def fetch_file_content(
    owner: str,
    repo: str,
    path: str,
    ref: Optional[str] = None,
    *,
    client: Optional[GitHubAPIClient] = None,
) -> bytes:
    """
    Fetch one file content via GitHub API (read-only). Uses scraping token.
    """
    if client is None:
        client = get_github_client(use="scraping")
    content, _ = client.get_file_content(owner, repo, path, ref=ref)
    return content


def upload_file(
    owner: str,
    repo: str,
    dest_path: str,
    local_file_path: str | Path,
    commit_message: Optional[str] = None,
    branch: str = "main",
    *,
    client: Optional[GitHubAPIClient] = None,
) -> Optional[dict]:
    """
    Upload a local file to a GitHub repo via Contents API (create or update).
    Uses write token. Returns API response dict or None on failure.
    """
    local_file_path = Path(local_file_path)
    if not local_file_path.is_file():
        logger.error("Local file not found or is a directory: %s", local_file_path)
        return None
    if client is None:
        client = get_github_client(use="write")
    content = local_file_path.read_bytes()
    content_base64 = base64.b64encode(content).decode("utf-8")
    if commit_message is None:
        commit_message = f"Add {local_file_path.name}"
    sha = client.get_file_sha(owner, repo, dest_path, ref=branch)
    try:
        return client.create_or_update_file(
            owner,
            repo,
            dest_path,
            content_base64,
            commit_message,
            branch=branch,
            sha=sha,
        )
    except Exception as e:
        logger.exception(
            "Upload file %s to %s/%s/%s failed: %s",
            local_file_path,
            owner,
            repo,
            dest_path,
            e,
        )
        return None


def get_commit_file_changes(
    repo_dir: str | Path,
    parent_sha: str,
    commit_sha: str,
    *,
    patch_size_limit: Optional[int] = None,
) -> list[dict]:
    """
    Get full list of changed files between parent and commit via git diff.

    For initial commits (no parent), pass git's empty tree SHA as parent_sha
    to get all files as "added" with full patches.

    Returns list of file dicts matching GitHub API 'files' shape:
    - filename: str
    - previous_filename: str (for renames and copies)
    - status: str (added, copied, removed, modified, renamed, changed, unmerged, unknown, broken)
    - additions: int
    - deletions: int
    - patch: str

    Args:
        repo_dir: Path to cloned repo
        parent_sha: Parent commit SHA, or empty tree SHA for initial commits
        commit_sha: Commit SHA
        patch_size_limit: Optional max chars per patch. None or 0 = no limit (fetch full patch).
    """
    repo_dir = Path(repo_dir)

    # Get file status (A=added, M=modified, D=deleted, R=renamed, etc.)
    # Use utf-8 encoding so git diff output (e.g. patches) decodes correctly on Windows
    try:
        result_status = subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir),
                "diff",
                "--name-status",
                f"{parent_sha}..{commit_sha}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=GIT_DIFF_TIMEOUT,
        )

        # Get additions/deletions per file
        result_numstat = subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir),
                "diff",
                "--numstat",
                f"{parent_sha}..{commit_sha}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=GIT_DIFF_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        logger.warning(
            "git diff timed out after %ss (repo_dir=%s, %s..%s): %s",
            GIT_DIFF_TIMEOUT,
            repo_dir,
            parent_sha[:7],
            commit_sha[:7],
            e,
        )
        raise

    # Parse status (format: "M\tpath" or "R100\told_path\tnew_path" or "C100\told_path\tnew_path")
    # Git diff --name-status: A=Added, C=Copied, D=Deleted, M=Modified, R=Renamed,
    # T=type changed, U=Unmerged, X=Unknown, B=Broken pairing.
    status_map = {}
    _status_names = {
        "A": "added",
        "C": "copied",
        "D": "removed",
        "M": "modified",
        "R": "renamed",
        "T": "changed",  # type (e.g. file → symlink)
        "U": "unmerged",
        "X": "unknown",
        "B": "broken",
    }
    for line in result_status.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        status_code = parts[0]
        first_char = status_code[0] if status_code else "M"

        if first_char in ("R", "C") and len(parts) >= 3:
            # Rename / Copy: "R100\told_path\tnew_path" or "C100\told_path\tnew_path"
            old_path = parts[1]
            new_path = parts[2]
            status_name = _status_names.get(first_char, "modified")
            status_map[new_path] = (status_name, old_path)
        else:
            path = parts[1]
            status_name = _status_names.get(first_char, "modified")
            status_map[path] = (status_name, None)

    # Parse numstat (format: "additions\tdeletions\tpath")
    # For renames, path can be "old => new"; use new path as key to match status_map
    numstat_map = {}
    for line in result_numstat.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds = parts[0]
        dels = parts[1]
        path = parts[2]
        if " => " in path:
            brace_match = re.search(r"\{([^{}]*) => ([^{}]*)\}", path)
            if brace_match:
                path = (
                    path[: brace_match.start()]
                    + brace_match.group(2)
                    + path[brace_match.end() :]
                )
            else:
                path = path.split(" => ", 1)[1].strip()
        # Handle binary files (marked as "-")
        additions = 0 if adds == "-" else int(adds)
        deletions = 0 if dels == "-" else int(dels)
        numstat_map[path] = (additions, deletions)

    # Build file list
    files = []
    for filename, (status, prev_filename) in status_map.items():
        additions, deletions = numstat_map.get(filename, (0, 0))

        # Get per-file patch
        patch = ""
        if status != "removed":  # Can't get patch for removed files in some cases
            try:
                result_patch = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo_dir),
                        "diff",
                        f"{parent_sha}..{commit_sha}",
                        "--",
                        filename,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                    timeout=30,
                )
                patch = result_patch.stdout

                # Apply size limit if specified
                if (
                    patch_size_limit is not None
                    and patch_size_limit > 0
                    and len(patch) > patch_size_limit
                ):
                    patch = patch[:patch_size_limit] + "\n... (truncated)"
            except (
                subprocess.TimeoutExpired,
                subprocess.CalledProcessError,
            ) as e:
                logger.warning("Failed to get patch for %s: %s", filename, e)
                patch = ""

        file_dict = {
            "filename": filename,
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "patch": patch,
        }

        if prev_filename:
            file_dict["previous_filename"] = prev_filename

        files.append(file_dict)

    logger.debug(
        "Extracted %d file changes from git diff %s..%s",
        len(files),
        parent_sha[:7],
        commit_sha[:7],
    )
    return files
