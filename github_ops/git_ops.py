"""
Git and content operations for GitHub: clone, push, fetch one file.
All apps use this module (and github_ops.client) for GitHub operations.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

from github_ops.client import GitHubAPIClient
from github_ops.tokens import get_github_client, get_github_token

logger = logging.getLogger(__name__)


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
