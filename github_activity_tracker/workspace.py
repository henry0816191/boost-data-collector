"""
Workspace paths for github_activity_tracker: JSON cache for commits, issues, PRs.

Layout: workspace/github_activity_tracker/<owner>/<repo>/
  - commits/<hash>.json
  - issues/<issue_number>.json
  - prs/<pr_number>.json
"""

from pathlib import Path

from config.workspace import get_workspace_path

_APP_SLUG = "github_activity_tracker"


def get_workspace_root() -> Path:
    """Return this app's workspace directory (e.g. workspace/github_activity_tracker/)."""
    return get_workspace_path(_APP_SLUG)


def get_repo_dir(owner: str, repo: str) -> Path:
    """Return workspace/github_activity_tracker/<owner>/<repo>/; creates dirs if missing."""
    path = get_workspace_root() / owner / repo
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_commits_dir(owner: str, repo: str) -> Path:
    """Return .../<owner>/<repo>/commits/; creates if missing."""
    path = get_repo_dir(owner, repo) / "commits"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_issues_dir(owner: str, repo: str) -> Path:
    """Return .../<owner>/<repo>/issues/; creates if missing."""
    path = get_repo_dir(owner, repo) / "issues"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_prs_dir(owner: str, repo: str) -> Path:
    """Return .../<owner>/<repo>/prs/; creates if missing."""
    path = get_repo_dir(owner, repo) / "prs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_commit_json_path(owner: str, repo: str, commit_sha: str) -> Path:
    """Path for commits/<hash>.json (parent dir created on first write)."""
    return get_commits_dir(owner, repo) / f"{commit_sha}.json"


def get_issue_json_path(owner: str, repo: str, issue_number: int) -> Path:
    """Path for issues/<issue_number>.json."""
    return get_issues_dir(owner, repo) / f"{issue_number}.json"


def get_pr_json_path(owner: str, repo: str, pr_number: int) -> Path:
    """Path for prs/<pr_number>.json."""
    return get_prs_dir(owner, repo) / f"{pr_number}.json"


def iter_existing_commit_jsons(owner: str, repo: str):
    """Yield path for each commits/*.json under workspace/<owner>/<repo>/."""
    commits_dir = get_workspace_root() / owner / repo / "commits"
    if not commits_dir.is_dir():
        return
    for path in commits_dir.glob("*.json"):
        yield path


def iter_existing_issue_jsons(owner: str, repo: str):
    """Yield path for each issues/*.json under workspace/<owner>/<repo>/."""
    issues_dir = get_workspace_root() / owner / repo / "issues"
    if not issues_dir.is_dir():
        return
    for path in issues_dir.glob("*.json"):
        yield path


def iter_existing_pr_jsons(owner: str, repo: str):
    """Yield path for each prs/*.json under workspace/<owner>/<repo>/."""
    prs_dir = get_workspace_root() / owner / repo / "prs"
    if not prs_dir.is_dir():
        return
    for path in prs_dir.glob("*.json"):
        yield path


# --- Raw source (tmp: workspace/raw/github_activity_tracker); will be removed in product ---


def get_raw_source_root() -> Path:
    """Return workspace/raw/github_activity_tracker/; creates dirs if missing."""
    path = get_workspace_path("raw") / "github_activity_tracker"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_source_repo_dir(owner: str, repo: str) -> Path:
    """Return .../raw/github_activity_tracker/<owner>/<repo>/; creates if missing."""
    path = get_raw_source_root() / owner / repo
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_source_commits_dir(owner: str, repo: str) -> Path:
    """Return .../<owner>/<repo>/commits/; creates if missing."""
    path = get_raw_source_repo_dir(owner, repo) / "commits"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_source_issues_dir(owner: str, repo: str) -> Path:
    """Return .../<owner>/<repo>/issues/; creates if missing."""
    path = get_raw_source_repo_dir(owner, repo) / "issues"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_source_prs_dir(owner: str, repo: str) -> Path:
    """Return .../<owner>/<repo>/prs/; creates if missing."""
    path = get_raw_source_repo_dir(owner, repo) / "prs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_source_commit_path(owner: str, repo: str, commit_sha: str) -> Path:
    """Path for raw source commits/<sha>.json."""
    return get_raw_source_commits_dir(owner, repo) / f"{commit_sha}.json"


def get_raw_source_issue_path(owner: str, repo: str, issue_number: int) -> Path:
    """Path for raw source issues/<number>.json."""
    return get_raw_source_issues_dir(owner, repo) / f"{issue_number}.json"


def get_raw_source_pr_path(owner: str, repo: str, pr_number: int) -> Path:
    """Path for raw source prs/<number>.json."""
    return get_raw_source_prs_dir(owner, repo) / f"{pr_number}.json"
