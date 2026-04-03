"""Publish Clang markdown export to GitHub via a persistent clone."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError

from github_ops.git_ops import clone_repo, prepare_repo_for_pull, pull, push as git_push
from github_ops.tokens import get_github_token
from operations.md_ops.github_export import detect_stale_titled_paths

logger = logging.getLogger(__name__)

_GITHUB_OWNER_REPO_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def _validate_github_slug(label: str, value: str) -> str:
    """Return stripped owner or repo name, or raise CommandError if unsafe or invalid."""
    v = (value or "").strip()
    if not v:
        raise CommandError(f"Invalid GitHub {label}: empty")
    if v in (".", ".."):
        raise CommandError(f"Invalid GitHub {label}: {v!r}")
    if "/" in v or "\\" in v:
        raise CommandError(f"Invalid GitHub {label}: {v!r}")
    if Path(v).is_absolute():
        raise CommandError(f"Invalid GitHub {label}: {v!r}")
    if not _GITHUB_OWNER_REPO_SLUG.fullmatch(v):
        raise CommandError(f"Invalid GitHub {label}: {v!r}")
    return v


def _reset_hard_to_upstream(clone_dir: Path, remote: str, branch: str) -> None:
    """Match origin/<branch> after pull so unpushed local commits from a failed push are dropped."""
    ref = f"{remote}/{branch}"
    try:
        subprocess.run(
            ["git", "-C", str(clone_dir), "reset", "--hard", ref],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as e:
        err = ((e.stderr or "") + (e.stdout or "")).strip() or str(e)
        raise CommandError(f"Could not reset clone to {ref}: {err}") from e


def _copy_md_tree(md_output_dir: Path, clone_dir: Path) -> None:
    """Copy all files under md_output_dir into clone_dir (preserve relative paths)."""
    md_output_dir = md_output_dir.resolve()
    clone_dir = clone_dir.resolve()
    for path in md_output_dir.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.relative_to(md_output_dir).parts:
            continue
        rel = path.relative_to(md_output_dir)
        dest = clone_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)


def publish_clang_markdown(
    md_output_dir: Path,
    owner: str,
    repo: str,
    branch: str,
    new_files: dict[str, str],
) -> None:
    """
    Clone (if needed) at RAW_DIR/clang_github_tracker/<owner>/<repo>, fetch/clean/pull,
    align to origin/<branch>, remove stale titled .md in md_export and clone, overlay
    md_export into the clone, commit and push.

    Uses get_github_token(use=\"write\") and settings GIT_AUTHOR_* for the commit.
    """
    owner = _validate_github_slug("owner", owner)
    repo = _validate_github_slug("repo", repo)

    publish_root = (Path(settings.RAW_DIR) / "clang_github_tracker").resolve()
    clone_dir = (publish_root / owner / repo).resolve()
    try:
        clone_dir.relative_to(publish_root)
    except ValueError as e:
        raise CommandError(
            f"Publish clone path escapes clang publish root: {clone_dir}"
        ) from e

    md_output_dir = md_output_dir.resolve()
    if (
        clone_dir == md_output_dir
        or clone_dir in md_output_dir.parents
        or md_output_dir in clone_dir.parents
    ):
        raise CommandError(
            "Markdown output directory must not overlap with the publish clone path: "
            f"{clone_dir}"
        )

    # Private CLANG_GITHUB_CONTEXT_* repos need a PAT that can read them (clone/pull)
    # and push; get_github_token("write") uses GITHUB_TOKEN_WRITE or GITHUB_TOKEN.
    token = get_github_token(use="write")
    git_user_name = (
        getattr(settings, "GIT_AUTHOR_NAME", None) or ""
    ).strip() or "unknown"
    git_user_email = (
        getattr(settings, "GIT_AUTHOR_EMAIL", None) or ""
    ).strip() or "unknown@noreply.github.com"

    repo_slug = f"{owner}/{repo}"
    logger.info("Publishing Clang markdown to %s (%s)...", repo_slug, branch)
    logger.info(
        "Publish git operations use the write token (GITHUB_TOKEN_WRITE, else "
        "GITHUB_TOKEN). For a private target repo, that PAT must be granted access "
        "to %s.",
        repo_slug,
    )

    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    if not clone_dir.exists() or not (clone_dir / ".git").is_dir():
        if clone_dir.exists():
            shutil.rmtree(clone_dir)
        logger.info("Cloning %s to %s", repo_slug, clone_dir)
        try:
            clone_repo(repo_slug, clone_dir, token=token)
        except subprocess.CalledProcessError as e:
            tail = ((e.stderr or "") + (e.stdout or "")).strip()
            hint = (
                "Clone already uses get_github_token(use='write') (GITHUB_TOKEN_WRITE "
                "or GITHUB_TOKEN). Verify CLANG_GITHUB_CONTEXT_REPO_OWNER / _NAME, "
                "and that this PAT can access the repo: for a private repo use a "
                "classic PAT with 'repo' scope or a fine-grained PAT with access to "
                "that repository. GitHub often returns 'not found' when the token "
                "lacks access."
            )
            logger.error(
                "clang_github_tracker publish: git clone failed: %s", tail or e
            )
            raise CommandError(
                f"Git clone failed for {repo_slug}: {tail or e.returncode}. {hint}"
            ) from e

    logger.info("Bootstrapping clone before pull: fetch, clean, reset (%s)", clone_dir)
    try:
        prepare_repo_for_pull(clone_dir, remote="origin", token=token)
    except subprocess.CalledProcessError as e:
        err = ((e.stderr or "") + (e.stdout or "")).strip() or str(e)
        logger.error(
            "clang_github_tracker publish: prepare clone for pull failed "
            "(clone_dir=%s, branch=%s): %s",
            clone_dir,
            branch,
            err,
            exc_info=e,
        )
        raise CommandError(f"Failed to prepare clone for pull: {err}") from e

    logger.info("Pulling latest for %s", clone_dir)
    try:
        pull(clone_dir, branch=branch, token=token)
    except subprocess.CalledProcessError as e:
        err = ((e.stderr or "") + (e.stdout or "")).strip() or str(e)
        logger.error(
            "clang_github_tracker publish: git pull failed (clone_dir=%s, branch=%s): %s",
            clone_dir,
            branch,
            err,
            exc_info=e,
        )
        raise CommandError(f"Git pull failed: {err}") from e

    logger.info("Resetting clone to origin/%s (discard unpushed commits)", branch)
    _reset_hard_to_upstream(clone_dir, "origin", branch)

    stale_md = detect_stale_titled_paths(md_output_dir, new_files)
    stale_clone = detect_stale_titled_paths(clone_dir, new_files)
    all_stale = sorted(set(stale_md) | set(stale_clone))

    for rel in all_stale:
        for base in (md_output_dir, clone_dir):
            p = base / rel
            if p.is_file():
                p.unlink()

    if all_stale:
        logger.info(
            "clang_github_tracker publish: removed %s stale titled file(s).",
            len(all_stale),
        )

    _copy_md_tree(md_output_dir, clone_dir)

    try:
        git_push(
            clone_dir,
            remote="origin",
            branch=branch,
            commit_message="chore: update Clang issues/PRs markdown",
            token=token,
            git_user_name=git_user_name,
            git_user_email=git_user_email,
        )
    except subprocess.CalledProcessError as e:
        err = ((e.stderr or "") + (e.stdout or "")).strip() or str(e)
        logger.error("clang_github_tracker publish: git push failed: %s", err)
        raise CommandError(f"Git push failed: {err}") from e

    logger.info("Clang markdown published successfully to %s.", repo_slug)
