"""
Git and content operations for GitHub: clone, pull, push (with optional add/commit),
fetch one file, upload file or folder.
All apps use this module (and github_ops.client) for GitHub operations.
"""

from __future__ import annotations

import base64
import logging
import os
import random
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

import requests

from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_client, get_github_token

logger = logging.getLogger(__name__)

# Fewer workers to avoid GitHub secondary rate limit (403 when too many concurrent requests)
_UPLOAD_FOLDER_MAX_WORKERS = 4
_UPLOAD_FOLDER_BLOB_RETRIES = 5
# Cap concurrent blob POSTs across all executor threads (primary + secondary limit relief)
_UPLOAD_FOLDER_BLOB_MAX_CONCURRENT = 3
# Max seconds to sleep in one wait after 403 (avoid unbounded sleeps from bad headers)
_UPLOAD_FOLDER_403_MAX_SLEEP_SEC = 900

_blob_post_semaphore = threading.BoundedSemaphore(_UPLOAD_FOLDER_BLOB_MAX_CONCURRENT)
_thread_local = threading.local()


def _get_worker_session(token: str) -> requests.Session:
    """One session per thread for parallel blob creation; keyed by token so different tokens get separate sessions."""
    if (
        not hasattr(_thread_local, "session")
        or getattr(_thread_local, "_token", None) != token
    ):
        s = requests.Session()
        s.headers.update(
            {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        _thread_local.session = s
        _thread_local._token = token
    return _thread_local.session


def _wait_seconds_for_github_403(r: requests.Response, attempt: int) -> float:
    """Sleep duration after a 403 from GitHub (primary limit, Retry-After, or fallback)."""
    max_sleep = float(_UPLOAD_FOLDER_403_MAX_SLEEP_SEC)
    h = r.headers

    remaining = h.get("X-RateLimit-Remaining")
    reset_raw = h.get("X-RateLimit-Reset")
    try:
        if remaining is not None and int(remaining) == 0 and reset_raw is not None:
            reset_ts = int(reset_raw)
            wait = max(1.0, float(reset_ts) - time.time())
            wait += random.uniform(0, 2)
            return min(wait, max_sleep)
    except (TypeError, ValueError):
        pass

    ra = h.get("Retry-After")
    if ra is not None:
        try:
            wait = float(ra)
            if wait < 1.0:
                wait = 1.0
            wait += random.uniform(0, 1)
            return min(wait, max_sleep)
        except (TypeError, ValueError):
            pass

    base = 60.0 * (2.0**attempt)
    wait = min(base + random.uniform(0, 2), max_sleep)
    return wait


def _create_blob_with_retry(
    base: str, token: str, repo_path: str, local_path: Path
) -> tuple[str, str]:
    """Create one blob; retry on failure (including 403 rate limit). Returns (repo_path, blob_sha).
    Reads file content from local_path on demand to avoid loading all files into memory.
    """
    session = _get_worker_session(token)
    content = local_path.read_bytes()
    content_b64 = base64.b64encode(content).decode("ascii")
    blob_data = {"content": content_b64, "encoding": "base64"}
    url = f"{base}/git/blobs"
    last_err = None
    for attempt in range(_UPLOAD_FOLDER_BLOB_RETRIES):
        try:
            with _blob_post_semaphore:
                r = session.post(url, json=blob_data, timeout=30)
            if r.status_code == 403:
                wait_sec = _wait_seconds_for_github_403(r, attempt)
                if attempt < _UPLOAD_FOLDER_BLOB_RETRIES - 1:
                    logger.warning(
                        "Blob upload 403 (rate limit), waiting %.1fs before retry (%s)",
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
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < _UPLOAD_FOLDER_BLOB_RETRIES - 1:
                time.sleep(1)
    raise last_err or RuntimeError(f"Blob creation failed for {repo_path}")


# Timeout (seconds) for top-level git diff subprocess calls (--name-status, --numstat)
GIT_DIFF_TIMEOUT = 60
# Timeout (seconds) for git clone and push (network I/O)
GIT_CMD_TIMEOUT_SECONDS = 300


def _url_with_token(url: str, token: str) -> str:
    """Inject credentials into a GitHub HTTPS URL for Git over HTTPS.

    Uses ``x-access-token:<token>`` as the userinfo segment. Required for
    fine-grained PATs (``github_pat_...``); classic PATs work with this form too.
    """
    if not token:
        return url
    auth = f"x-access-token:{token}"
    return re.sub(
        r"^(https://)(github\.com/)",
        r"\1" + auth + r"@\2",
        url,
        count=1,
    )


def sanitize_git_output(text: str) -> str:
    """Redact credentials from git stderr/stdout snippets before logging.

    Masks GitHub HTTPS PAT forms and other userinfo-in-URL patterns so logs do not
    leak tokens when clone/push echoes the remote URL.
    """
    if not text:
        return text
    out = re.sub(
        r"(?i)(x-access-token:)[^@\s]+(@)",
        r"\1***\2",
        text,
    )
    out = re.sub(
        r"(?i)(https?://)[^/\s?#]+@",
        r"\1<redacted>@",
        out,
    )
    return out


def clone_repo(
    url_or_slug: str,
    dest_dir: str | Path,
    *,
    token: Optional[str] = None,
    depth: Optional[int] = None,
) -> None:
    """
    Clone a GitHub repo.

    If ``token`` is omitted, uses the scraping token (``get_github_token(use="scraping")``).
    Callers cloning **private** repos must pass ``token=get_github_token(use="write")``
    (or equivalent) so GitHub authenticates with a PAT that has repository access.
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
    safe_url_or_slug = sanitize_git_output(url_or_slug)
    logger.info("Cloning %s -> %s", safe_url_or_slug, dest_dir)
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
    except subprocess.TimeoutExpired as e:
        safe_cmd: list[str] = ["git", "clone", safe_url_or_slug, str(dest_dir)]
        if depth is not None:
            safe_cmd.extend(["--depth", str(depth)])
        logger.warning(
            "git clone timed out after %ss (%s -> %s)",
            GIT_CMD_TIMEOUT_SECONDS,
            safe_url_or_slug,
            dest_dir,
        )
        raise subprocess.TimeoutExpired(
            safe_cmd,
            e.timeout,
            output=None if e.output is None else sanitize_git_output(e.output),
            stderr=None if e.stderr is None else sanitize_git_output(e.stderr),
        ) from None
    except subprocess.CalledProcessError as e:
        err_tail = ((e.stderr or "") + (e.stdout or ""))[-500:]
        safe_err_tail = sanitize_git_output(err_tail)
        logger.warning(
            "git clone failed (%s -> %s), returncode=%s, stderr/stdout_tail=%r",
            safe_url_or_slug,
            dest_dir,
            e.returncode,
            safe_err_tail,
        )
        # Never re-raise with the real cmd or raw output: they may embed the token.
        safe_cmd: list[str] = ["git", "clone", safe_url_or_slug, str(dest_dir)]
        if depth is not None:
            safe_cmd.extend(["--depth", str(depth)])
        safe_stdout = sanitize_git_output(e.stdout or "")
        safe_stderr = sanitize_git_output(e.stderr or "")
        raise subprocess.CalledProcessError(
            e.returncode, safe_cmd, safe_stdout, safe_stderr
        ) from None


def push(
    repo_dir: str | Path,
    remote: str = "origin",
    branch: Optional[str] = None,
    *,
    commit_message: Optional[str] = None,
    add_paths: Optional[list[str | Path]] = None,
    token: Optional[str] = None,
    git_user_name: Optional[str] = None,
    git_user_email: Optional[str] = None,
) -> None:
    """
    Push to remote. Uses push token by default.
    Always runs git add, git commit, then push. Uses commit_message if provided,
    otherwise "Auto commit in <YYYY-MM-DD HH:MM:SS UTC>". add_paths: paths to add
    (relative to repo_dir); if None, adds all (git add .).

    git_user_name / git_user_email: if set, passed only to the ``git commit`` subprocess
    via GIT_AUTHOR_* / GIT_COMMITTER_* env vars (does not modify repo ``git config``).
    Any existing GIT_AUTHOR_* / GIT_COMMITTER_* entries are removed from the commit
    environment first so ambient or Django-set values are not inherited when unset.
    """
    repo_dir = Path(repo_dir)
    if token is None:
        token = get_github_token(use="push")

    add_targets = ["."] if add_paths is None else [str(Path(p)) for p in add_paths]
    message = (
        commit_message
        if commit_message is not None
        else f"Auto commit in {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    logger.info("Adding and committing in %s", repo_dir)
    subprocess.run(
        ["git", "-C", str(repo_dir), "add", *add_targets],
        check=True,
        capture_output=True,
        text=True,
    )
    commit_env = dict(os.environ)
    for _key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        commit_env.pop(_key, None)
    if git_user_name:
        commit_env["GIT_AUTHOR_NAME"] = git_user_name
        commit_env["GIT_COMMITTER_NAME"] = git_user_name
    if git_user_email:
        commit_env["GIT_AUTHOR_EMAIL"] = git_user_email
        commit_env["GIT_COMMITTER_EMAIL"] = git_user_email
    commit_result = subprocess.run(
        ["git", "-C", str(repo_dir), "commit", "-m", message],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=commit_env,
    )
    if commit_result.returncode != 0:
        out = (commit_result.stderr or "") + (commit_result.stdout or "")
        if "nothing to commit" not in out:
            raise subprocess.CalledProcessError(
                commit_result.returncode,
                ["git", "commit", "-m", message],
                commit_result.stdout,
                commit_result.stderr,
            )
        logger.info("Nothing to commit in %s", repo_dir)

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
    safe_push_cmd = ["git", "-C", str(repo_dir), "push", remote_url]
    if branch:
        safe_push_cmd.append(branch)
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
    except subprocess.TimeoutExpired as e:
        logger.warning(
            "git push timed out after %ss (%s)",
            GIT_CMD_TIMEOUT_SECONDS,
            repo_dir,
        )
        raise subprocess.TimeoutExpired(
            safe_push_cmd,
            e.timeout,
            output=None if e.output is None else sanitize_git_output(e.output),
            stderr=None if e.stderr is None else sanitize_git_output(e.stderr),
        ) from None
    except subprocess.CalledProcessError as e:
        err_tail = ((e.stderr or "") + (e.stdout or ""))[-500:]
        safe_err_tail = sanitize_git_output(err_tail)
        logger.warning(
            "git push failed (%s), returncode=%s, stderr/stdout_tail=%r",
            repo_dir,
            e.returncode,
            safe_err_tail,
        )
        safe_stdout = sanitize_git_output(e.stdout or "")
        safe_stderr = sanitize_git_output(e.stderr or "")
        raise subprocess.CalledProcessError(
            e.returncode, safe_push_cmd, safe_stdout, safe_stderr
        ) from None


def pull(
    repo_dir: str | Path,
    branch: Optional[str] = None,
    *,
    remote: str = "origin",
    token: Optional[str] = None,
) -> None:
    """
    Pull from remote. Uses push token by default.
    branch: branch to pull (e.g. main); if given, checks out that branch first then pulls.
    """
    repo_dir = Path(repo_dir)
    if token is None:
        token = get_github_token(use="push")
    if branch:
        subprocess.run(
            ["git", "-C", str(repo_dir), "checkout", branch],
            check=True,
            capture_output=True,
            text=True,
        )
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "get-url", remote],
        capture_output=True,
        text=True,
        check=True,
    )
    remote_url = result.stdout.strip()
    auth_url = _url_with_token(remote_url, token)
    cmd = ["git", "-C", str(repo_dir), "pull", auth_url]
    if branch:
        cmd.append(branch)
    logger.info("Pulling %s %s", repo_dir, branch or "(current)")
    safe_pull_cmd = ["git", "-C", str(repo_dir), "pull", remote_url]
    if branch:
        safe_pull_cmd.append(branch)
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
    except subprocess.TimeoutExpired as e:
        logger.warning(
            "git pull timed out after %ss (%s)",
            GIT_CMD_TIMEOUT_SECONDS,
            repo_dir,
        )
        raise subprocess.TimeoutExpired(
            safe_pull_cmd,
            e.timeout,
            output=None if e.output is None else sanitize_git_output(e.output),
            stderr=None if e.stderr is None else sanitize_git_output(e.stderr),
        ) from None
    except subprocess.CalledProcessError as e:
        err_tail = ((e.stderr or "") + (e.stdout or ""))[-500:]
        safe_err_tail = sanitize_git_output(err_tail)
        logger.warning(
            "git pull failed (%s), returncode=%s, stderr/stdout_tail=%r",
            repo_dir,
            e.returncode,
            safe_err_tail,
        )
        safe_stdout = sanitize_git_output(e.stdout or "")
        safe_stderr = sanitize_git_output(e.stderr or "")
        raise subprocess.CalledProcessError(
            e.returncode, safe_pull_cmd, safe_stdout, safe_stderr
        ) from None


def prepare_repo_for_pull(
    repo_dir: str | Path,
    *,
    remote: str = "origin",
    token: Optional[str] = None,
) -> None:
    """
    Fetch remote branch refs (prune), remove untracked files, and reset the working tree.

    Use before checkout/pull on a reused clone that may have local changes or lack
    remote-tracking refs for branches that exist only on the remote.
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
    auth_url = _url_with_token(remote_url, token or "")

    logger.info("Fetching %s refs (prune) in %s", remote, repo_dir)
    fetch_cmd = [
        "git",
        "-C",
        str(repo_dir),
        "fetch",
        auth_url,
        f"+refs/heads/*:refs/remotes/{remote}/*",
        "--prune",
    ]
    safe_fetch_cmd = [
        "git",
        "-C",
        str(repo_dir),
        "fetch",
        remote_url,
        f"+refs/heads/*:refs/remotes/{remote}/*",
        "--prune",
    ]
    try:
        subprocess.run(
            fetch_cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_CMD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        logger.warning(
            "git fetch timed out after %ss (%s)",
            GIT_CMD_TIMEOUT_SECONDS,
            repo_dir,
        )
        raise subprocess.TimeoutExpired(
            safe_fetch_cmd,
            e.timeout,
            output=None if e.output is None else sanitize_git_output(e.output),
            stderr=None if e.stderr is None else sanitize_git_output(e.stderr),
        ) from None
    except subprocess.CalledProcessError as e:
        err_tail = ((e.stderr or "") + (e.stdout or ""))[-500:]
        safe_err_tail = sanitize_git_output(err_tail)
        logger.warning(
            "git fetch failed (%s), returncode=%s, stderr/stdout_tail=%r",
            repo_dir,
            e.returncode,
            safe_err_tail,
        )
        safe_stdout = sanitize_git_output(e.stdout or "")
        safe_stderr = sanitize_git_output(e.stderr or "")
        raise subprocess.CalledProcessError(
            e.returncode, safe_fetch_cmd, safe_stdout, safe_stderr
        ) from None
    logger.info("Running git clean -fd in %s", repo_dir)
    subprocess.run(
        ["git", "-C", str(repo_dir), "clean", "-fd"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    logger.info("Running git reset --hard in %s", repo_dir)
    subprocess.run(
        ["git", "-C", str(repo_dir), "reset", "--hard"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


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


def get_remote_tree(
    owner: str,
    repo: str,
    branch: str = "master",
    *,
    token: Optional[str] = None,
) -> list[dict]:
    """Fetch the full recursive Git tree for a branch via the GitHub API.

    Returns a list of tree item dicts (path, sha, type, mode, size).
    Returns an empty list if the repo/branch is empty or on any error.

    GitHub limits recursive trees to 100,000 entries and 7 MB. If the tree is
    larger, the API sets "truncated": true and returns a partial list. This
    function logs a warning when truncated; callers (e.g. detect_renames) may
    then miss some paths.

    Args:
        owner: Repository owner.
        repo: Repository name.
        branch: Branch name (default: "master").
        token: GitHub token (default: write token from settings).
    """
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
    try:
        r = session.get(f"{base}/git/ref/heads/{branch}", timeout=30)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        commit_sha = r.json()["object"]["sha"]

        r = session.get(f"{base}/git/commits/{commit_sha}", timeout=30)
        r.raise_for_status()
        tree_sha = r.json()["tree"]["sha"]

        r = session.get(f"{base}/git/trees/{tree_sha}?recursive=1", timeout=60)
        r.raise_for_status()
        data = r.json()
        tree = data.get("tree") or []
        if data.get("truncated"):
            logger.warning(
                "get_remote_tree: tree for %s/%s (branch %s) was truncated by GitHub "
                "(limit 100,000 entries / 7 MB); returned %s entries. Rename detection may be incomplete.",
                owner,
                repo,
                branch,
                len(tree),
            )
        return tree
    except Exception as e:
        logger.warning("get_remote_tree failed for %s/%s: %s", owner, repo, e)
        return []


# macOS resource-fork / metadata files to exclude from uploads (e.g. ._filename)
_UPLOAD_IGNORE_PREFIX = "._"


def list_remote_directory(
    owner: str,
    repo: str,
    branch: str,
    dir_path: str,
    *,
    token: Optional[str] = None,
) -> list[str]:
    """List file paths in a single directory via GitHub GraphQL API (non-recursive).

    Uses one GraphQL request per directory instead of multiple REST Git Tree calls.
    Use this for large repos (100k+ files) where get_remote_tree() would be truncated.

    Args:
        owner: Repository owner.
        repo: Repository name.
        branch: Branch name.
        dir_path: Repository-relative directory path (e.g. "boost/issues/2024/2024-03").
            Use "" for the repository root.
        token: GitHub token (default: write token from settings).

    Returns:
        List of full repo-relative paths for each file (blob) in that directory.
        Empty list if the path does not exist or on error.
    """
    if token is None:
        token = get_github_token(use="write")
    try:
        return _list_remote_directory_graphql(owner, repo, branch, dir_path, token)
    except Exception as e:
        logger.debug(
            "list_remote_directory failed for %s/%s path=%r: %s",
            owner,
            repo,
            dir_path,
            e,
        )
        return []


def _list_remote_directory_graphql(
    owner: str,
    repo: str,
    branch: str,
    dir_path: str,
    token: str,
) -> list[str]:
    """List blobs in one directory via a single GraphQL query."""
    if dir_path and dir_path.strip():
        expression = f"{branch}:{dir_path.rstrip('/')}"
    else:
        expression = f"{branch}:"
    query = """
    query($owner: String!, $repo: String!, $expression: String!) {
      repository(owner: $owner, name: $repo) {
        object(expression: $expression) {
          ... on Tree {
            entries {
              name
              type
            }
          }
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {"owner": owner, "repo": repo, "expression": expression},
    }
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    )
    r = session.post("https://api.github.com/graphql", json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data and data["errors"]:
        raise RuntimeError(data["errors"][0].get("message", str(data["errors"])))
    obj = (data.get("data") or {}).get("repository", {}).get("object")
    if not obj:
        return []
    entries = obj.get("entries") or []
    prefix = dir_path.rstrip("/") if dir_path and dir_path.strip() else ""
    return [
        f"{prefix}/{e['name']}" if prefix else e["name"]
        for e in entries
        if e.get("type") == "blob"
    ]


def upload_folder_to_github(
    local_folder: str | Path,
    owner: str,
    repo: str,
    commit_message: str = "Upload files",
    branch: str = "main",
    *,
    delete_paths: Optional[list[str]] = None,
    client: Optional[GitHubAPIClient] = None,
    token: Optional[str] = None,
) -> dict:
    """
    Upload a local folder to a GitHub repo via Git Data API (blobs, tree, commit, ref).
    Uses write token. Creates one commit with all files from the folder.
    No need to clone the repo; upload is done entirely via the API.
    Note: Performance scales with file count (e.g. ~200 files can take 2+ minutes).

    Token resolution: When client is provided, an explicit token argument takes
    precedence over client.token (token = token or client.token). When client
    is None, token defaults to get_github_token(use="write") if not passed.

    Args:
        local_folder: Local directory to upload.
        owner: Repository owner.
        repo: Repository name.
        commit_message: Commit message.
        branch: Target branch (default: "main").
        delete_paths: Optional list of repo-relative file paths to delete in the
            same commit (e.g. old-titled MD files when a title changes). Each path
            is added to the Git tree with sha=null to remove it.
        client: Optional pre-built GitHubAPIClient.
        token: Optional GitHub token override.

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
            if token == getattr(client, "token", None):
                session = client.session
            else:
                session = requests.Session()
                session.headers.update(dict(client.session.headers))
                session.headers.update(
                    {
                        "Authorization": f"token {token}",
                        "Accept": "application/vnd.github.v3+json",
                    }
                )
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

        # Collect (repo_path, local_path) for all files (paths only; content read in worker).
        # Skip macOS metadata files (._*).
        file_items = []
        for root, _, files in os.walk(local_folder):
            for file in files:
                if file.startswith(_UPLOAD_IGNORE_PREFIX):
                    continue
                local_path = Path(root) / file
                repo_path = local_path.relative_to(local_folder).as_posix()
                file_items.append((repo_path, local_path))

        # Create blobs in parallel (each worker reads and encodes its file on demand)
        tree_items = []
        blob_failures = []
        with ThreadPoolExecutor(max_workers=_UPLOAD_FOLDER_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_create_blob_with_retry, base, token, rp, lp): (rp, lp)
                for rp, lp in file_items
            }
            for fut in as_completed(futures):
                rp, lp = futures[fut]
                try:
                    repo_path, blob_sha = fut.result()
                    tree_items.append(
                        {
                            "path": repo_path,
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob_sha,
                        }
                    )
                except Exception as e:
                    blob_failures.append((rp, e))
        if blob_failures:
            created_shas = [t["sha"] for t in tree_items]
            failed_paths = [p for p, _ in blob_failures]
            raise RuntimeError(
                f"Blob creation failed for {len(blob_failures)} file(s): {failed_paths}. "
                f"Created blobs (now orphaned): {created_shas[:5]}{'...' if len(created_shas) > 5 else ''}."
            ) from blob_failures[0][1]

        # Add deletion entries for renamed/removed files (sha=null removes from tree)
        for path in delete_paths or []:
            tree_items.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": None}
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
        r = session.patch(f"{base}/git/refs/heads/{branch}", json=ref_data, timeout=30)
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
        logger.exception("upload_folder_to_github failed")
        return {"success": False, "message": str(e)}


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
