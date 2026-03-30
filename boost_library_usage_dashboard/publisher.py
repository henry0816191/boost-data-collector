"""Publish Boost library usage dashboard artifacts to a GitHub repository."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError

from github_ops.git_ops import clone_repo, pull, push

logger = logging.getLogger(__name__)


def publish_dashboard(
    output_dir: Path,
    owner: str,
    repo: str,
    branch: str,
) -> None:
    """
    Publish using a persistent clone at raw/boost_library_usage_dashboard/<owner>/<repo>.
    Clone if missing, pull, sync ``develop/`` from output_dir, commit, push.

    Uses ``settings.GITHUB_TOKEN_WRITE`` for clone/pull/push and
    ``settings.GIT_AUTHOR_NAME`` / ``settings.GIT_AUTHOR_EMAIL`` for the commit
    identity (via env vars on ``git commit`` only).
    """
    clone_dir = Path(settings.RAW_DIR) / "boost_library_usage_dashboard" / owner / repo
    clone_dir = clone_dir.resolve()
    output_dir = output_dir.resolve()
    if (
        clone_dir == output_dir
        or clone_dir in output_dir.parents
        or output_dir in clone_dir.parents
    ):
        raise CommandError(
            "Workspace output directory must not overlap with the publish clone path: "
            f"{clone_dir}"
        )

    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    token = (getattr(settings, "GITHUB_TOKEN_WRITE", None) or "").strip() or None
    git_user_name = (getattr(settings, "GIT_AUTHOR_NAME", None) or "unknown").strip()
    git_user_email = (
        getattr(settings, "GIT_AUTHOR_EMAIL", None) or "unknown@noreply.github.com"
    ).strip()

    repo_slug = f"{owner}/{repo}"
    logger.info("Publishing dashboard artifacts to %s (%s)...", repo_slug, branch)

    if not clone_dir.exists() or not (clone_dir / ".git").is_dir():
        if clone_dir.exists():
            shutil.rmtree(clone_dir)
        logger.info("Cloning %s to %s", repo_slug, clone_dir)
        clone_repo(repo_slug, clone_dir, token=token)

    logger.info("Pulling latest for %s", clone_dir)
    pull(clone_dir, branch=branch, token=token)

    for child in clone_dir.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and child.name == "develop":
            shutil.rmtree(child)

    publish_subdir = clone_dir / "develop"
    publish_subdir.mkdir(parents=True, exist_ok=True)

    for child in output_dir.iterdir():
        dest = publish_subdir / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            if child.suffix != ".html":
                continue
            shutil.copy2(child, dest)

    commit_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    commit_message = f"Update Boost library usage dashboard artifacts ({commit_time})"
    push(
        clone_dir,
        remote="origin",
        branch=branch,
        commit_message=commit_message,
        token=token,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
    )
    logger.info("Dashboard artifacts published successfully to %s.", repo_slug)
