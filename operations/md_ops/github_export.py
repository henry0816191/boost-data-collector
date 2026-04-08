"""
Export synced GitHub issues/PRs as Markdown files into a folder structure
suitable for pushing to a target GitHub repository.

Public API:
    write_md_files(owner, repo, issue_numbers, pr_numbers, output_dir, folder_prefix)
    detect_renames(remote_tree, new_files) -> list[str]
    detect_renames_from_dirs(owner, repo, branch, new_files, *, token) -> list[str]
      Use for large repos (100k+ files); lists only the directories we write to.
    detect_stale_titled_paths(base_dir, new_files) -> list[str]
      Local Path listing (md_export or clone); same #n title-rename rules; no API.

Folder structure produced:
    <output_dir>/<folder_prefix>/issues/YYYY/YYYY-MM/#<number> - <title>.md
    <output_dir>/<folder_prefix>/pull_requests/YYYY/YYYY-MM/#<number> - <title>.md

When folder_prefix is "" (clang style), the prefix directory is omitted:
    <output_dir>/issues/YYYY/YYYY-MM/#<number> - <title>.md
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from github_ops import list_remote_directory
from github_activity_tracker.workspace import (
    get_raw_source_issue_path,
    get_raw_source_pr_path,
)
from operations.md_ops.issue_to_md import issue_json_to_md
from operations.md_ops.pr_to_md import pr_json_to_md

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')
_NUMBER_PREFIX = re.compile(r"^#(\d+) - ")


def _safe_title(title: str) -> str:
    """Sanitize a title for use as a filename component (max 100 chars)."""
    return _UNSAFE_CHARS.sub("", title).strip()[:100]


def _md_path(
    output_dir: Path,
    folder_prefix: str,
    entity_type: str,
    created_at: Optional[datetime],
    number: int,
    title: str,
) -> Path:
    """Build the full output path for one issue or PR markdown file.

    Args:
        output_dir: Root temp directory.
        folder_prefix: Repo prefix ("boost", "boost.algorithm", or "" for no prefix).
        entity_type: "issues" or "pull_requests".
        created_at: Created date used for YYYY/YYYY-MM path segments (falls back to today).
        number: Issue or PR number.
        title: Issue or PR title (will be sanitized and truncated).
    """
    if created_at is None:
        d = datetime.now(timezone.utc).replace(tzinfo=None)
    elif created_at.tzinfo is not None:
        d = created_at.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        d = created_at
    filename = f"#{number} - {_safe_title(title)}.md"
    parts: list[Path | str] = [output_dir]
    if folder_prefix:
        parts.append(folder_prefix)
    parts += [entity_type, d.strftime("%Y"), d.strftime("%Y-%m"), filename]
    return Path(*parts)


def write_md_files(
    owner: str,
    repo: str,
    issue_numbers: list[int],
    pr_numbers: list[int],
    output_dir: Path,
    folder_prefix: str = "",
) -> dict[str, str]:
    """Read raw JSONs, convert to Markdown, write to output_dir.

    Args:
        owner: GitHub owner of the source repo.
        repo: GitHub repo name of the source repo.
        issue_numbers: Issue numbers to export.
        pr_numbers: PR numbers to export.
        output_dir: Root directory for output files.
        folder_prefix: Prefix subdirectory (e.g. "boost", "boost.algorithm").
            Empty string means no prefix (clang style).

    Returns:
        Dict mapping repo-relative path (e.g. "boost/issues/2024/2024-03/#1 - title.md")
        to the absolute local file path. Used by detect_renames to find old files.
    """
    new_files: dict[str, str] = {}

    for number in issue_numbers:
        raw_path = get_raw_source_issue_path(owner, repo, number)
        if not raw_path.exists():
            logger.warning(
                "write_md_files: raw issue JSON not found: %s (skipping #%s)",
                raw_path,
                number,
            )
            continue
        try:
            issue_data = json.loads(raw_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("write_md_files: failed to read %s: %s", raw_path, e)
            continue

        info = issue_data.get("issue_info") or issue_data
        title = (info.get("title") or "").strip() or f"issue-{number}"
        created_at_raw = info.get("created_at")
        created_at = _parse_dt(created_at_raw)

        out_path = _md_path(
            output_dir, folder_prefix, "issues", created_at, number, title
        )
        try:
            md_content = issue_json_to_md(issue_data)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md_content, encoding="utf-8")
            repo_rel = out_path.relative_to(output_dir).as_posix()
            new_files[repo_rel] = str(out_path)
            logger.debug("write_md_files: wrote issue #%s → %s", number, repo_rel)
        except Exception as e:
            logger.warning("write_md_files: failed to write issue #%s: %s", number, e)

    for number in pr_numbers:
        raw_path = get_raw_source_pr_path(owner, repo, number)
        if not raw_path.exists():
            logger.warning(
                "write_md_files: raw PR JSON not found: %s (skipping #%s)",
                raw_path,
                number,
            )
            continue
        try:
            pr_data = json.loads(raw_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("write_md_files: failed to read %s: %s", raw_path, e)
            continue

        info = pr_data.get("pr_info") or pr_data
        title = (info.get("title") or "").strip() or f"pr-{number}"
        created_at_raw = info.get("created_at")
        created_at = _parse_dt(created_at_raw)

        out_path = _md_path(
            output_dir,
            folder_prefix,
            "pull_requests",
            created_at,
            number,
            title,
        )
        try:
            md_content = pr_json_to_md(pr_data)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md_content, encoding="utf-8")
            repo_rel = out_path.relative_to(output_dir).as_posix()
            new_files[repo_rel] = str(out_path)
            logger.debug("write_md_files: wrote PR #%s → %s", number, repo_rel)
        except Exception as e:
            logger.warning("write_md_files: failed to write PR #%s: %s", number, e)

    return new_files


def _stale_titled_paths_vs_listing(
    new_files: dict[str, str],
    files_by_dir: dict[str, list[tuple[str, str]]],
    *,
    log_prefix: str = "stale_titled",
) -> list[str]:
    """Paths to remove: same directory + same #n - prefix as a new file, different filename."""
    if not new_files or not files_by_dir:
        return []

    delete_paths: list[str] = []
    for new_repo_rel in new_files:
        new_filename = new_repo_rel.rsplit("/", 1)[-1]
        new_dir = new_repo_rel.rsplit("/", 1)[0] if "/" in new_repo_rel else ""

        m = _NUMBER_PREFIX.match(new_filename)
        if not m:
            continue
        number_str = m.group(1)
        prefix = f"#{number_str} - "

        for listed_filename, listed_path in files_by_dir.get(new_dir, []):
            if listed_filename.startswith(prefix) and listed_filename != new_filename:
                logger.debug(
                    "%s: %r → %r (title changed, will delete old)",
                    log_prefix,
                    listed_path,
                    new_repo_rel,
                )
                delete_paths.append(listed_path)

    return sorted(set(delete_paths))


def detect_renames(
    remote_tree: list[dict],
    new_files: dict[str, str],
) -> list[str]:
    """Find remote files that must be deleted because an issue/PR title changed.

    For each file being uploaded (keyed by repo-relative path), extract the issue/PR
    number from the filename and scan the remote tree for any existing file with the
    same number in the same directory. If the remote filename differs from the new one,
    it is a renamed file that must be deleted.

    Args:
        remote_tree: List of tree item dicts from get_remote_tree().
        new_files: Dict of {repo_relative_path: local_path} returned by write_md_files().

    Returns:
        List of repo-relative remote paths to delete.
    """
    if not remote_tree or not new_files:
        return []

    # Build a lookup: directory → list of (filename, full_path) for blob entries
    files_by_dir: dict[str, list[tuple[str, str]]] = {}
    for item in remote_tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if not path:
            continue
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        filename = path.rsplit("/", 1)[-1]
        files_by_dir.setdefault(parent, []).append((filename, path))

    return _stale_titled_paths_vs_listing(
        new_files, files_by_dir, log_prefix="detect_renames"
    )


def detect_renames_from_dirs(
    owner: str,
    repo: str,
    branch: str,
    new_files: dict[str, str],
    *,
    token: Optional[str] = None,
) -> list[str]:
    """Find remote paths to delete (old-titled files) by listing only affected directories.

    Use this for large repos (100k+ files, 1GB+) where get_remote_tree() would be
    truncated. Lists each directory we write to via list_remote_directory(), so
    only a small number of API calls are made.

    Args:
        owner: Repository owner (markdown publish target).
        repo: Repository name.
        branch: Branch name.
        new_files: Dict of {repo_relative_path: local_path} from write_md_files().
        token: GitHub token (default: write token from settings).

    Returns:
        List of repo-relative paths to delete.
    """
    if not new_files:
        return []

    dirs = set()
    for repo_rel in new_files:
        if "/" in repo_rel:
            dirs.add(repo_rel.rsplit("/", 1)[0])
        else:
            dirs.add("")

    files_by_dir: dict[str, list[tuple[str, str]]] = {}
    for dir_path in sorted(dirs):
        for remote_path in list_remote_directory(
            owner, repo, branch, dir_path, token=token
        ):
            filename = remote_path.rsplit("/", 1)[-1]
            remote_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else ""
            files_by_dir.setdefault(remote_dir, []).append((filename, remote_path))

    return _stale_titled_paths_vs_listing(
        new_files, files_by_dir, log_prefix="detect_renames_from_dirs"
    )


def detect_stale_titled_paths(
    base_dir: Path,
    new_files: dict[str, str],
) -> list[str]:
    """Find paths under base_dir to delete (old title) using local directory listings.

    Same rules as detect_renames_from_dirs, but lists each affected directory with
    Path.iterdir (no GitHub API). Use on md_export and on a clone after pull.

    Args:
        base_dir: Root to resolve paths against (md_export root or repo clone root).
        new_files: Dict of {repo_relative_path: local_path} from write_md_files().

    Returns:
        Paths relative to base_dir (posix) that should be unlinked.
    """
    base_dir = base_dir.resolve()
    if not new_files:
        return []

    dirs: set[str] = set()
    for repo_rel in new_files:
        if "/" in repo_rel:
            dirs.add(repo_rel.rsplit("/", 1)[0])
        else:
            dirs.add("")

    files_by_dir: dict[str, list[tuple[str, str]]] = {}
    for dir_path in dirs:
        scan = base_dir if dir_path == "" else base_dir / dir_path
        if not scan.is_dir():
            continue
        for p in scan.iterdir():
            if p.name.startswith(".") or p.name == ".git":
                continue
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            rel = p.relative_to(base_dir).as_posix()
            parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
            files_by_dir.setdefault(parent, []).append((p.name, rel))

    return _stale_titled_paths_vs_listing(
        new_files, files_by_dir, log_prefix="detect_stale_titled_paths"
    )


def _parse_dt(value: object) -> Optional[datetime]:
    """Parse an ISO datetime string to a naive datetime (UTC). Returns None on failure."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, AttributeError):
        return None
