"""
Git and content operations for GitHub: clone, push, fetch one file, upload file or folder.
All apps use this module (and github_ops.client) for GitHub operations.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_client, get_github_token

logger = logging.getLogger(__name__)

# Fewer workers to avoid GitHub secondary rate limit (403 when too many concurrent requests)
_UPLOAD_FOLDER_MAX_WORKERS = 8
_UPLOAD_FOLDER_BLOB_RETRIES = 5
_UPLOAD_FOLDER_403_WAIT_SEC = 5
_thread_local = threading.local()


def _get_worker_session(base: str, token: str) -> requests.Session:
    """One session per thread for parallel blob creation."""
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(
            {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        _thread_local.session = s
    return _thread_local.session


def _create_blob_with_retry(
    base: str, token: str, repo_path: str, content_b64: str
) -> tuple[str, str]:
    """Create one blob; retry on failure (including 403 rate limit). Returns (repo_path, blob_sha)."""
    session = _get_worker_session(base, token)
    blob_data = {"content": content_b64, "encoding": "base64"}
    url = f"{base}/git/blobs"
    last_err = None
    for attempt in range(_UPLOAD_FOLDER_BLOB_RETRIES):
        try:
            r = session.post(url, json=blob_data, timeout=30)
            if r.status_code == 403:
                # GitHub secondary rate limit; wait and retry (cap at our constant)
                wait_sec = _UPLOAD_FOLDER_403_WAIT_SEC
                try:
                    from_header = int(r.headers.get("Retry-After", wait_sec))
                    wait_sec = min(from_header, _UPLOAD_FOLDER_403_WAIT_SEC)
                except (TypeError, ValueError):
                    pass
                if attempt < _UPLOAD_FOLDER_BLOB_RETRIES - 1:
                    logger.warning(
                        "Blob upload 403 (rate limit), waiting %ss before retry (%s)",
                        wait_sec,
                        repo_path,
                    )
                    time.sleep(wait_sec)
                    continue
                last_err = requests.exceptions.HTTPError(
                    "403 Forbidden (rate limit)", response=r
                )
                continue
            r.raise_for_status()
            return (repo_path, r.json()["sha"])
        except requests.exceptions.HTTPError as e:
            last_err = e
            if attempt < _UPLOAD_FOLDER_BLOB_RETRIES - 1:
                time.sleep(2)
        except Exception as e:
            last_err = e
            if attempt < _UPLOAD_FOLDER_BLOB_RETRIES - 1:
                time.sleep(1)
    raise last_err


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
    subprocess.run(cmd, check=True, capture_output=True, text=True)


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
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "get-url", remote],
        capture_output=True,
        text=True,
        check=True,
    )
    remote_url = result.stdout.strip()
    push_url = _url_with_token(remote_url, token)
    cmd = ["git", "-C", str(repo_dir), "push", push_url]
    if branch:
        cmd.append(branch)
    logger.info("Pushing %s %s", repo_dir, branch or "(current)")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


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
        logger.error(
            "Local file not found or is a directory: %s", local_file_path
        )
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


def upload_folder_to_github(
    local_folder: str | Path,
    owner: str,
    repo: str,
    commit_message: str = "Upload files",
    branch: str = "main",
    *,
    client: Optional[GitHubAPIClient] = None,
    token: Optional[str] = None,
) -> dict:
    """
    Upload a local folder to a GitHub repo via Git Data API (blobs, tree, commit, ref).
    Uses write token. Creates one commit with all files from the folder.

    Returns:
        {"success": True, "message": "..."} on success,
        {"success": False, "message": "..."} on failure.
    """
    local_folder = Path(local_folder)
    if not local_folder.is_dir():
        return {
            "success": False,
            "message": f"Not a directory: {local_folder}",
        }

    try:
        if client is not None:
            token = token or client.token
            base = f"{client.rest_base_url}/repos/{owner}/{repo}"
            session = client.session
        else:
            if token is None:
                token = get_github_token(use="write")
            base = f"https://api.github.com/repos/{owner}/{repo}"
            session = requests.Session()
            session.headers.update(
                {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                }
            )

        # Get latest commit
        r = session.get(f"{base}/git/ref/heads/{branch}", timeout=30)
        r.raise_for_status()
        commit_sha = r.json()["object"]["sha"]

        # Get commit tree
        r = session.get(f"{base}/git/commits/{commit_sha}", timeout=30)
        r.raise_for_status()
        base_tree = r.json()["tree"]["sha"]

        # Collect (repo_path, content_b64) for all files
        file_items = []
        for root, _, files in os.walk(local_folder):
            for file in files:
                local_path = Path(root) / file
                repo_path = local_path.relative_to(local_folder).as_posix()
                content = local_path.read_bytes()
                content_b64 = base64.b64encode(content).decode("ascii")
                file_items.append((repo_path, content_b64))

        # Create blobs in parallel (one request per file; when one finishes, next starts)
        tree_items = []
        with ThreadPoolExecutor(
            max_workers=_UPLOAD_FOLDER_MAX_WORKERS
        ) as executor:
            futures = {
                executor.submit(
                    _create_blob_with_retry, base, token, rp, b64
                ): (rp, b64)
                for rp, b64 in file_items
            }
            for fut in as_completed(futures):
                repo_path, blob_sha = fut.result()
                tree_items.append(
                    {
                        "path": repo_path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha,
                    }
                )

        tree_data = {"base_tree": base_tree, "tree": tree_items}
        r = session.post(f"{base}/git/trees", json=tree_data, timeout=30)
        r.raise_for_status()
        new_tree = r.json()["sha"]

        commit_data = {
            "message": commit_message,
            "tree": new_tree,
            "parents": [commit_sha],
        }
        r = session.post(f"{base}/git/commits", json=commit_data, timeout=30)
        r.raise_for_status()
        new_commit = r.json()["sha"]

        ref_data = {"sha": new_commit}
        r = session.patch(
            f"{base}/git/refs/heads/{branch}", json=ref_data, timeout=30
        )
        r.raise_for_status()

        logger.info(
            "Upload folder %s to %s/%s (branch %s) complete.",
            local_folder,
            owner,
            repo,
            branch,
        )
        return {
            "success": True,
            "message": f"Uploaded {local_folder} to {owner}/{repo} (branch {branch})",
        }
    except Exception as e:
        logger.exception("upload_folder_to_github failed: %s", e)
        return {"success": False, "message": str(e)}
