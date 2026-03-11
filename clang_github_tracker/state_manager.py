"""
State for clang_github_tracker: last sync dates per entity (commits, issues, PRs).

Stored in workspace/clang_github_activity/state.json.
When state file is missing, it can be computed by scanning raw/github_activity_tracker/llvm/llvm-project.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from clang_github_tracker.workspace import get_state_path, get_raw_repo_dir

logger = logging.getLogger(__name__)

# Keys in state JSON
KEY_LAST_COMMIT_DATE = "last_commit_date"
KEY_LAST_ISSUE_DATE = "last_issue_date"
KEY_LAST_PR_DATE = "last_pr_date"


def parse_iso(s: str | None) -> datetime | None:
    """Parse ISO datetime string; returns None if missing or invalid."""
    if not s or not isinstance(s, str) or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _to_iso(dt: datetime | None) -> str | None:
    """Return datetime as ISO string with Z suffix, or None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def load_state() -> dict[str, str | None]:
    """
    Load state from workspace/clang_github_activity/state.json.

    Returns:
        - {} (empty dict): file missing, invalid, read error, or loaded object is empty/all-None
          → invalid; ensure_state_file_exists will recompute from raw.
        - Dict with keys last_commit_date, last_issue_date, last_pr_date (values str or None):
          valid state file (at least one non-None date); None means no previous sync for that entity.
    """
    path = get_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        # Treat empty or all-None as invalid so ensure_state_file_exists can recompute from raw
        if not any(
            (
                data.get(KEY_LAST_COMMIT_DATE),
                data.get(KEY_LAST_ISSUE_DATE),
                data.get(KEY_LAST_PR_DATE),
            )
        ):
            return {}
        return {
            KEY_LAST_COMMIT_DATE: data.get(KEY_LAST_COMMIT_DATE),
            KEY_LAST_ISSUE_DATE: data.get(KEY_LAST_ISSUE_DATE),
            KEY_LAST_PR_DATE: data.get(KEY_LAST_PR_DATE),
        }
    except Exception as e:
        logger.warning("Failed to load state from %s: %s", path, e)
        return {}


def save_state(
    last_commit_date: datetime | None = None,
    last_issue_date: datetime | None = None,
    last_pr_date: datetime | None = None,
    *,
    merge: bool = True,
) -> None:
    """Write state to workspace/clang_github_activity/state.json. If merge=True, load existing and update only provided keys."""
    path = get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if merge:
        current = load_state()
        if last_commit_date is not None:
            current[KEY_LAST_COMMIT_DATE] = _to_iso(last_commit_date)
        if last_issue_date is not None:
            current[KEY_LAST_ISSUE_DATE] = _to_iso(last_issue_date)
        if last_pr_date is not None:
            current[KEY_LAST_PR_DATE] = _to_iso(last_pr_date)
        data = current
    else:
        data = {
            KEY_LAST_COMMIT_DATE: _to_iso(last_commit_date),
            KEY_LAST_ISSUE_DATE: _to_iso(last_issue_date),
            KEY_LAST_PR_DATE: _to_iso(last_pr_date),
        }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.debug("Saved state to %s", path)


def _latest_date_from_commit_json(path: Path) -> datetime | None:
    """Read a commit JSON file and return the author/committer date, or None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        commit = data.get("commit") or {}
        author = commit.get("author") or commit.get("committer") or {}
        date_str = author.get("date")
        return parse_iso(date_str)
    except Exception:
        return None


def _latest_date_from_issue_or_pr_json(path: Path) -> datetime | None:
    """Read an issue or PR JSON file and return updated_at or created_at, or None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Top-level or nested under issue_info / pr_info
        for obj in [data, data.get("issue_info"), data.get("pr_info")]:
            if not isinstance(obj, dict):
                continue
            date_str = obj.get("updated_at") or obj.get("created_at")
            dt = parse_iso(date_str)
            if dt is not None:
                return dt
        return None
    except Exception:
        return None


def compute_state_from_raw() -> dict[str, str | None]:
    """
    Scan raw/github_activity_tracker/<owner>/<repo> for commits, issues, prs
    and return state dict with last_commit_date, last_issue_date, last_pr_date (ISO or None).
    If the raw folder does not exist, returns all Nones (caller can write state.json from this).
    """
    root = get_raw_repo_dir(create=False)
    result: dict[str, str | None] = {
        KEY_LAST_COMMIT_DATE: None,
        KEY_LAST_ISSUE_DATE: None,
        KEY_LAST_PR_DATE: None,
    }
    if not root.is_dir():
        return result

    # Commits
    commits_dir = root / "commits"
    if commits_dir.is_dir():
        latest_commit: datetime | None = None
        for p in commits_dir.glob("*.json"):
            dt = _latest_date_from_commit_json(p)
            if dt and (latest_commit is None or dt > latest_commit):
                latest_commit = dt
        result[KEY_LAST_COMMIT_DATE] = _to_iso(latest_commit)

    # Issues
    issues_dir = root / "issues"
    if issues_dir.is_dir():
        latest_issue: datetime | None = None
        for p in issues_dir.glob("*.json"):
            dt = _latest_date_from_issue_or_pr_json(p)
            if dt and (latest_issue is None or dt > latest_issue):
                latest_issue = dt
        result[KEY_LAST_ISSUE_DATE] = _to_iso(latest_issue)

    # PRs
    prs_dir = root / "prs"
    if prs_dir.is_dir():
        latest_pr: datetime | None = None
        for p in prs_dir.glob("*.json"):
            dt = _latest_date_from_issue_or_pr_json(p)
            if dt and (latest_pr is None or dt > latest_pr):
                latest_pr = dt
        result[KEY_LAST_PR_DATE] = _to_iso(latest_pr)

    return result


def ensure_state_file_exists() -> dict[str, str | None]:
    """
    If state file does not exist, ensure state.json exists:
    - If raw folder exists: compute state from raw and write state.json.
    - If raw folder does not exist: write state.json with {last_commit_date: null, last_issue_date: null, last_pr_date: null}.
    If state file exists, load and return. If the file content is not a valid object (empty or invalid JSON), retry once by recomputing from raw and overwriting.

    Returns:
        - {} (empty dict): error (e.g. write failed after retry). Caller should log and finish.
        - Dict with last_commit_date, last_issue_date, last_pr_date (str or None): state exists; use it (None = fetch from beginning).
    """
    path = get_state_path()
    if path.exists():
        state = load_state()
        if state:
            return state
        # File exists but content is not a valid object (empty or invalid); retry once by recomputing from raw
        logger.warning(
            "state.json is empty or not a valid object; recomputing from raw once."
        )
        computed = compute_state_from_raw()
        try:
            path.write_text(json.dumps(computed, indent=2), encoding="utf-8")
            logger.info(
                "Rewrote state file from raw: last_commit=%s last_issue=%s last_pr=%s",
                computed.get(KEY_LAST_COMMIT_DATE),
                computed.get(KEY_LAST_ISSUE_DATE),
                computed.get(KEY_LAST_PR_DATE),
            )
            return computed
        except OSError as e:
            logger.warning("Failed to rewrite state file %s: %s", path, e)
            return {}
    computed = compute_state_from_raw()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(computed, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning(
            "Failed to write state file %s: %s; proceeding with no state.",
            path,
            e,
        )
        return {}
    logger.info(
        "Created state file from raw scan: last_commit=%s last_issue=%s last_pr=%s",
        computed.get(KEY_LAST_COMMIT_DATE),
        computed.get(KEY_LAST_ISSUE_DATE),
        computed.get(KEY_LAST_PR_DATE),
    )
    return computed


def resolve_start_end_dates(
    from_date: datetime | None,
    to_date: datetime | None,
) -> tuple[datetime | None, datetime | None, datetime | None, datetime] | None:
    """
    Resolve start dates for commits, issues, PRs and end_date.

    - If from_date and to_date are both provided (CLI): use them for all three and for end.
    - Else: ensure state file exists (create from raw scan if missing), then use state's
      last_*_date + 1s as start per entity, and to_date or now as end.

    Returns:
        (start_commit, start_issue, start_pr, end_date) when state is valid.
        None when state is {} after one retry — error is logged; caller should finish.
    """
    if from_date is not None and to_date is not None:
        # CLI provided both: use for all
        if from_date.tzinfo is None:
            from_date = from_date.replace(tzinfo=timezone.utc)
        if to_date.tzinfo is None:
            to_date = to_date.replace(tzinfo=timezone.utc)
        return from_date, from_date, from_date, to_date

    state = ensure_state_file_exists()
    if not state:
        logger.error(
            "State unavailable (error reading state.json or raw folder). Cannot resolve dates; exiting."
        )
        return None
    now = datetime.now(timezone.utc)

    if to_date is None:
        to_date = now
    elif to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)

    def start_from_state(key: str) -> datetime | None:
        s = state.get(key)
        dt = parse_iso(s) if isinstance(s, str) else None
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt + timedelta(seconds=1)

    start_commit = (
        from_date if from_date is not None else start_from_state(KEY_LAST_COMMIT_DATE)
    )
    start_issue = (
        from_date if from_date is not None else start_from_state(KEY_LAST_ISSUE_DATE)
    )
    start_pr = (
        from_date if from_date is not None else start_from_state(KEY_LAST_PR_DATE)
    )

    return start_commit, start_issue, start_pr, to_date
