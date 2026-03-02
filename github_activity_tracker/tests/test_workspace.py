"""Tests for github_activity_tracker.workspace."""

import pytest
from pathlib import Path
from unittest.mock import patch

from github_activity_tracker.workspace import (
    get_clone_dir,
    get_clones_root,
    get_commits_dir,
    get_commit_json_path,
    get_issues_dir,
    get_issue_json_path,
    get_prs_dir,
    get_pr_json_path,
    get_raw_source_commits_dir,
    get_raw_source_commit_path,
    get_raw_source_issue_path,
    get_raw_source_issues_dir,
    get_raw_source_pr_path,
    get_raw_source_prs_dir,
    get_raw_source_repo_dir,
    get_raw_source_root,
    get_repo_dir,
    get_workspace_root,
    iter_existing_commit_jsons,
    iter_existing_issue_jsons,
    iter_existing_pr_jsons,
    remove_clone_dir,
)


@pytest.fixture
def mock_workspace_path(tmp_path):
    """Patch get_workspace_path to return tmp_path for this app."""
    with patch("github_activity_tracker.workspace.get_workspace_path") as m:
        m.return_value = tmp_path / "github_activity_tracker"
        yield m.return_value


# --- get_workspace_root ---


def test_get_workspace_root_returns_path(mock_workspace_path):
    """get_workspace_root returns Path from get_workspace_path(app_slug)."""

    root = get_workspace_root()
    assert root == mock_workspace_path


def test_get_workspace_root_calls_get_workspace_path(mock_workspace_path):
    """get_workspace_root calls get_workspace_path with app slug."""
    with patch("github_activity_tracker.workspace.get_workspace_path") as m:
        m.return_value = Path("/fake/workspace/github_activity_tracker")
        from github_activity_tracker.workspace import get_workspace_root

        get_workspace_root()
    m.assert_called_once()
    assert "github_activity_tracker" in str(m.call_args[0][0])


def test_get_workspace_root_is_path():
    """get_workspace_root return value is Path instance."""
    with patch("github_activity_tracker.workspace.get_workspace_path") as m:
        m.return_value = Path("/x")
        from github_activity_tracker.workspace import get_workspace_root

        root = get_workspace_root()
    assert isinstance(root, Path)


# --- get_repo_dir ---


def test_get_repo_dir_returns_owner_repo_path(mock_workspace_path):
    """get_repo_dir returns .../owner/repo/ and creates dirs."""
    path = get_repo_dir("boostorg", "boost")
    assert path == mock_workspace_path / "boostorg" / "boost"
    assert path.is_dir()


def test_get_repo_dir_creates_parents(mock_workspace_path):
    """get_repo_dir creates parent directories."""
    get_repo_dir("org", "repo")
    assert (mock_workspace_path / "org" / "repo").exists()


def test_get_repo_dir_idempotent(mock_workspace_path):
    """get_repo_dir can be called twice without error."""
    p1 = get_repo_dir("a", "b")
    p2 = get_repo_dir("a", "b")
    assert p1 == p2


# --- get_commits_dir ---


def test_get_commits_dir_returns_commits_subdir(mock_workspace_path):
    """get_commits_dir returns .../owner/repo/commits/."""
    path = get_commits_dir("o", "r")
    assert path == mock_workspace_path / "o" / "r" / "commits"
    assert path.is_dir()


def test_get_commits_dir_creates_dir(mock_workspace_path):
    """get_commits_dir creates commits directory."""
    path = get_commits_dir("owner", "repo")
    assert path.exists()
    assert path.name == "commits"


def test_get_commits_dir_idempotent(mock_workspace_path):
    """get_commits_dir second call returns same path."""
    p1 = get_commits_dir("x", "y")
    p2 = get_commits_dir("x", "y")
    assert p1 == p2


# --- get_issues_dir ---


def test_get_issues_dir_returns_issues_subdir(mock_workspace_path):
    """get_issues_dir returns .../owner/repo/issues/."""
    path = get_issues_dir("o", "r")
    assert path == mock_workspace_path / "o" / "r" / "issues"
    assert path.is_dir()


def test_get_issues_dir_creates_dir(mock_workspace_path):
    """get_issues_dir creates issues directory."""
    path = get_issues_dir("a", "b")
    assert path.exists()
    assert path.name == "issues"


def test_get_issues_dir_idempotent(mock_workspace_path):
    """get_issues_dir second call returns same path."""
    p1 = get_issues_dir("i", "j")
    p2 = get_issues_dir("i", "j")
    assert p1 == p2


# --- get_prs_dir ---


def test_get_prs_dir_returns_prs_subdir(mock_workspace_path):
    """get_prs_dir returns .../owner/repo/prs/."""
    path = get_prs_dir("o", "r")
    assert path == mock_workspace_path / "o" / "r" / "prs"
    assert path.is_dir()


def test_get_prs_dir_creates_dir(mock_workspace_path):
    """get_prs_dir creates prs directory."""
    path = get_prs_dir("p", "q")
    assert path.exists()
    assert path.name == "prs"


def test_get_prs_dir_idempotent(mock_workspace_path):
    """get_prs_dir second call returns same path."""
    p1 = get_prs_dir("p", "r")
    p2 = get_prs_dir("p", "r")
    assert p1 == p2


# --- get_commit_json_path ---


def test_get_commit_json_path_returns_commits_sha_json(mock_workspace_path):
    """get_commit_json_path returns .../commits/<sha>.json."""
    path = get_commit_json_path("owner", "repo", "abc123def")
    assert path == mock_workspace_path / "owner" / "repo" / "commits" / "abc123def.json"


def test_get_commit_json_path_does_not_create_file(mock_workspace_path):
    """get_commit_json_path returns path without creating the file."""
    path = get_commit_json_path("o", "r", "sha")
    assert path.suffix == ".json"
    assert path.name == "sha.json"


def test_get_commit_json_path_consistent(mock_workspace_path):
    """get_commit_json_path same args gives same path."""
    p1 = get_commit_json_path("a", "b", "c")
    p2 = get_commit_json_path("a", "b", "c")
    assert p1 == p2


# --- get_issue_json_path ---


def test_get_issue_json_path_returns_issues_num_json(mock_workspace_path):
    """get_issue_json_path returns .../issues/<number>.json."""
    path = get_issue_json_path("owner", "repo", 42)
    assert path == mock_workspace_path / "owner" / "repo" / "issues" / "42.json"


def test_get_issue_json_path_integer_number(mock_workspace_path):
    """get_issue_json_path accepts integer issue number."""
    path = get_issue_json_path("o", "r", 1)
    assert path.name == "1.json"


def test_get_issue_json_path_consistent(mock_workspace_path):
    """get_issue_json_path same args gives same path."""
    p1 = get_issue_json_path("x", "y", 10)
    p2 = get_issue_json_path("x", "y", 10)
    assert p1 == p2


# --- get_pr_json_path ---


def test_get_pr_json_path_returns_prs_num_json(mock_workspace_path):
    """get_pr_json_path returns .../prs/<number>.json."""
    path = get_pr_json_path("owner", "repo", 7)
    assert path == mock_workspace_path / "owner" / "repo" / "prs" / "7.json"


def test_get_pr_json_path_integer_number(mock_workspace_path):
    """get_pr_json_path accepts integer pr number."""
    path = get_pr_json_path("o", "r", 99)
    assert path.name == "99.json"


def test_get_pr_json_path_consistent(mock_workspace_path):
    """get_pr_json_path same args gives same path."""
    p1 = get_pr_json_path("a", "b", 5)
    p2 = get_pr_json_path("a", "b", 5)
    assert p1 == p2


# --- iter_existing_commit_jsons ---


def test_iter_existing_commit_jsons_empty_when_no_dir(mock_workspace_path):
    """iter_existing_commit_jsons yields nothing when commits dir does not exist."""
    listed = list(iter_existing_commit_jsons("nobody", "norepo"))
    assert listed == []


def test_iter_existing_commit_jsons_yields_json_files(mock_workspace_path):
    """iter_existing_commit_jsons yields Path for each *.json in commits/."""
    commits_dir = mock_workspace_path / "o" / "r" / "commits"
    commits_dir.mkdir(parents=True)
    (commits_dir / "a.json").write_text("{}")
    (commits_dir / "b.json").write_text("{}")
    paths = list(iter_existing_commit_jsons("o", "r"))
    assert len(paths) == 2
    names = {p.name for p in paths}
    assert names == {"a.json", "b.json"}


def test_iter_existing_commit_jsons_ignores_non_json(mock_workspace_path):
    """iter_existing_commit_jsons only yields *.json files."""
    commits_dir = mock_workspace_path / "o" / "r" / "commits"
    commits_dir.mkdir(parents=True)
    (commits_dir / "x.json").write_text("{}")
    (commits_dir / "x.txt").write_text("")
    paths = list(iter_existing_commit_jsons("o", "r"))
    assert len(paths) == 1
    assert paths[0].name == "x.json"


# --- iter_existing_issue_jsons ---


def test_iter_existing_issue_jsons_empty_when_no_dir(mock_workspace_path):
    """iter_existing_issue_jsons yields nothing when issues dir does not exist."""
    listed = list(iter_existing_issue_jsons("nobody", "norepo"))
    assert listed == []


def test_iter_existing_issue_jsons_yields_json_files(mock_workspace_path):
    """iter_existing_issue_jsons yields Path for each *.json in issues/."""
    issues_dir = mock_workspace_path / "o" / "r" / "issues"
    issues_dir.mkdir(parents=True)
    (issues_dir / "1.json").write_text("{}")
    paths = list(iter_existing_issue_jsons("o", "r"))
    assert len(paths) == 1
    assert paths[0].name == "1.json"


def test_iter_existing_issue_jsons_ignores_non_json(mock_workspace_path):
    """iter_existing_issue_jsons only yields *.json files."""
    issues_dir = mock_workspace_path / "o" / "r" / "issues"
    issues_dir.mkdir(parents=True)
    (issues_dir / "2.json").write_text("{}")
    (issues_dir / "readme.txt").write_text("")
    paths = list(iter_existing_issue_jsons("o", "r"))
    assert len(paths) == 1
    assert paths[0].name == "2.json"


# --- iter_existing_pr_jsons ---


def test_iter_existing_pr_jsons_empty_when_no_dir(mock_workspace_path):
    """iter_existing_pr_jsons yields nothing when prs dir does not exist."""
    listed = list(iter_existing_pr_jsons("nobody", "norepo"))
    assert listed == []


def test_iter_existing_pr_jsons_yields_json_files(mock_workspace_path):
    """iter_existing_pr_jsons yields Path for each *.json in prs/."""
    prs_dir = mock_workspace_path / "o" / "r" / "prs"
    prs_dir.mkdir(parents=True)
    (prs_dir / "3.json").write_text("{}")
    paths = list(iter_existing_pr_jsons("o", "r"))
    assert len(paths) == 1
    assert paths[0].name == "3.json"


def test_iter_existing_pr_jsons_ignores_non_json(mock_workspace_path):
    """iter_existing_pr_jsons only yields *.json files."""
    prs_dir = mock_workspace_path / "o" / "r" / "prs"
    prs_dir.mkdir(parents=True)
    (prs_dir / "4.json").write_text("{}")
    (prs_dir / "data.csv").write_text("")
    paths = list(iter_existing_pr_jsons("o", "r"))
    assert len(paths) == 1
    assert paths[0].name == "4.json"


# --- Raw source (workspace/raw/github_activity_tracker) ---


@pytest.fixture
def mock_raw_workspace_path(tmp_path):
    """Patch get_workspace_path so raw source root is tmp_path/raw/github_activity_tracker."""
    with patch("github_activity_tracker.workspace.get_workspace_path") as m:
        m.side_effect = lambda slug: tmp_path / slug
        yield tmp_path / "raw"


def test_get_raw_source_root_returns_path_and_creates_dir(
    mock_raw_workspace_path,
):
    """get_raw_source_root returns .../raw/github_activity_tracker/ and creates dirs."""
    root = get_raw_source_root()
    assert root == mock_raw_workspace_path / "github_activity_tracker"
    assert root.is_dir()


def test_get_raw_source_repo_dir_returns_owner_repo_subdir(
    mock_raw_workspace_path,
):
    """get_raw_source_repo_dir returns .../github_activity_tracker/<owner>/<repo>/."""
    path = get_raw_source_repo_dir("boostorg", "boost")
    assert (
        path
        == mock_raw_workspace_path / "github_activity_tracker" / "boostorg" / "boost"
    )
    assert path.is_dir()


def test_get_raw_source_commits_dir_returns_commits_subdir(
    mock_raw_workspace_path,
):
    """get_raw_source_commits_dir returns .../<owner>/<repo>/commits/."""
    path = get_raw_source_commits_dir("o", "r")
    assert (
        path
        == mock_raw_workspace_path / "github_activity_tracker" / "o" / "r" / "commits"
    )
    assert path.is_dir()


def test_get_raw_source_issues_dir_returns_issues_subdir(
    mock_raw_workspace_path,
):
    """get_raw_source_issues_dir returns .../<owner>/<repo>/issues/."""
    path = get_raw_source_issues_dir("o", "r")
    assert (
        path
        == mock_raw_workspace_path / "github_activity_tracker" / "o" / "r" / "issues"
    )
    assert path.is_dir()


def test_get_raw_source_prs_dir_returns_prs_subdir(mock_raw_workspace_path):
    """get_raw_source_prs_dir returns .../<owner>/<repo>/prs/."""
    path = get_raw_source_prs_dir("o", "r")
    assert (
        path == mock_raw_workspace_path / "github_activity_tracker" / "o" / "r" / "prs"
    )
    assert path.is_dir()


def test_get_raw_source_commit_path_returns_sha_json(mock_raw_workspace_path):
    """get_raw_source_commit_path returns .../commits/<sha>.json."""
    path = get_raw_source_commit_path("owner", "repo", "abc123def")
    assert (
        path
        == mock_raw_workspace_path
        / "github_activity_tracker"
        / "owner"
        / "repo"
        / "commits"
        / "abc123def.json"
    )


def test_get_raw_source_issue_path_returns_number_json(
    mock_raw_workspace_path,
):
    """get_raw_source_issue_path returns .../issues/<number>.json."""
    path = get_raw_source_issue_path("owner", "repo", 42)
    assert (
        path
        == mock_raw_workspace_path
        / "github_activity_tracker"
        / "owner"
        / "repo"
        / "issues"
        / "42.json"
    )


def test_get_raw_source_pr_path_returns_number_json(mock_raw_workspace_path):
    """get_raw_source_pr_path returns .../prs/<number>.json."""
    path = get_raw_source_pr_path("owner", "repo", 7)
    assert (
        path
        == mock_raw_workspace_path
        / "github_activity_tracker"
        / "owner"
        / "repo"
        / "prs"
        / "7.json"
    )


# --- get_clones_root, get_clone_dir ---


def test_get_clones_root_returns_clones_subdir(mock_workspace_path):
    """get_clones_root returns .../clones/ and creates it."""
    root = get_clones_root()
    assert root == mock_workspace_path / "clones"
    assert root.is_dir()


def test_get_clone_dir_returns_owner_repo_path(mock_workspace_path):
    """get_clone_dir returns .../clones/<owner>/<repo> and creates parent dir."""
    path = get_clone_dir("boostorg", "outcome")
    assert path == mock_workspace_path / "clones" / "boostorg" / "outcome"
    assert path.parent.is_dir()


# --- remove_clone_dir (Windows Access denied fix) ---


def test_remove_clone_dir_returns_true_when_path_missing(mock_workspace_path):
    """remove_clone_dir returns True when path does not exist."""
    missing = mock_workspace_path / "clones" / "nonexistent"
    assert remove_clone_dir(missing) is True


def test_remove_clone_dir_removes_dir_and_returns_true(mock_workspace_path):
    """remove_clone_dir removes directory and returns True (no read-only files)."""
    clone_path = mock_workspace_path / "clones" / "test_repo"
    clone_path.mkdir(parents=True)
    (clone_path / "file.txt").write_text("x")
    result = remove_clone_dir(clone_path)
    assert result is True
    assert not clone_path.exists()


def test_remove_clone_dir_returns_false_when_rmtree_raises(
    mock_workspace_path,
):
    """remove_clone_dir returns False when shutil.rmtree raises OSError (e.g. file locked)."""
    clone_path = mock_workspace_path / "clones" / "locked_repo"
    clone_path.mkdir(parents=True)
    with patch(
        "github_activity_tracker.workspace.shutil.rmtree",
        side_effect=OSError(5, "Access is denied"),
    ):
        result = remove_clone_dir(clone_path)
    assert result is False
    assert clone_path.exists()
