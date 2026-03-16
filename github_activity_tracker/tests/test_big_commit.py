"""Tests for github_activity_tracker big_commit (handle 300+ file commits)."""

from unittest.mock import patch

import pytest

from github_activity_tracker import big_commit


def test_is_commit_truncated_returns_true_for_300_files():
    """is_commit_truncated returns True when commit has exactly 300 files."""
    commit_data = {"files": [{"filename": f"file{i}.txt"} for i in range(300)]}
    assert big_commit.is_commit_truncated(commit_data) is True


def test_is_commit_truncated_returns_false_for_less_than_300_files():
    """is_commit_truncated returns False when commit has < 300 files."""
    commit_data = {"files": [{"filename": "file.txt"}]}
    assert big_commit.is_commit_truncated(commit_data) is False


def test_is_commit_truncated_returns_false_for_no_files():
    """is_commit_truncated returns False when commit has no files."""
    commit_data = {"files": []}
    assert big_commit.is_commit_truncated(commit_data) is False


def test_ensure_repo_cloned_clones_when_not_exists(tmp_path):
    """ensure_repo_cloned clones repo when it doesn't exist."""
    clone_path = tmp_path / "owner_repo"

    with patch(
        "github_activity_tracker.big_commit.get_clone_dir",
        return_value=clone_path,
    ):
        with patch("github_activity_tracker.big_commit.clone_repo") as clone_mock:
            with patch("github_activity_tracker.big_commit.register_clone"):
                result = big_commit.ensure_repo_cloned("owner", "repo")

    assert result == clone_path
    clone_mock.assert_called_once_with("owner/repo", clone_path)


def test_ensure_repo_cloned_fetches_when_exists(tmp_path):
    """ensure_repo_cloned runs git fetch when repo already exists."""
    clone_path = tmp_path / "owner_repo"
    clone_path.mkdir()
    (clone_path / ".git").mkdir()

    with patch(
        "github_activity_tracker.big_commit.get_clone_dir",
        return_value=clone_path,
    ):
        with patch("github_activity_tracker.big_commit.subprocess.run") as run_mock:
            with patch("github_activity_tracker.big_commit.register_clone"):
                result = big_commit.ensure_repo_cloned("owner", "repo")

    assert result == clone_path
    run_mock.assert_called_once()
    call_args = run_mock.call_args[0][0]
    assert "git" in call_args
    assert "fetch" in call_args


def test_ensure_repo_cloned_removes_existing_non_git_dir_before_clone(
    tmp_path,
):
    """ensure_repo_cloned removes existing dir when it has no .git (avoids clone exit 128)."""
    clone_path = tmp_path / "owner_repo"
    clone_path.mkdir()
    # No .git - not a git repo (e.g. leftover from failed clone)
    (clone_path / "some_file.txt").write_text("leftover")

    with patch(
        "github_activity_tracker.big_commit.get_clone_dir",
        return_value=clone_path,
    ):
        with patch(
            "github_activity_tracker.big_commit.remove_clone_dir",
            return_value=True,
        ) as remove_mock:
            with patch("github_activity_tracker.big_commit.clone_repo") as clone_mock:
                with patch("github_activity_tracker.big_commit.register_clone"):
                    result = big_commit.ensure_repo_cloned("owner", "repo")

    assert result == clone_path
    remove_mock.assert_called_once_with(clone_path)
    clone_mock.assert_called_once_with("owner/repo", clone_path)


def test_get_full_commit_files_returns_files_list(tmp_path):
    """get_full_commit_files clones repo and returns file list."""

    mock_files = [
        {
            "filename": "file1.txt",
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "patch": "",
        },
        {
            "filename": "file2.txt",
            "status": "added",
            "additions": 5,
            "deletions": 0,
            "patch": "",
        },
    ]

    with patch(
        "github_activity_tracker.big_commit.ensure_repo_cloned",
        return_value=tmp_path,
    ):
        with patch(
            "github_activity_tracker.big_commit.get_commit_file_changes",
            return_value=mock_files,
        ):
            files = big_commit.get_full_commit_files(
                "owner",
                "repo",
                commit_sha="commit_sha",
                parent_shas=["parent_sha"],
            )

    assert files == mock_files


def test_get_full_commit_files_initial_commit_diffs_against_empty_tree(
    tmp_path,
):
    """get_full_commit_files for initial commit diffs against empty tree and returns full file list."""
    mock_files = [
        {
            "filename": "file1.txt",
            "status": "added",
            "additions": 10,
            "deletions": 0,
            "patch": "",
        },
        {
            "filename": "file2.txt",
            "status": "added",
            "additions": 5,
            "deletions": 0,
            "patch": "",
        },
    ]
    with patch(
        "github_activity_tracker.big_commit.ensure_repo_cloned",
        return_value=tmp_path,
    ):
        with patch(
            "github_activity_tracker.big_commit.get_commit_file_changes",
            return_value=mock_files,
        ) as mock_get_changes:
            files = big_commit.get_full_commit_files(
                "owner", "repo", commit_sha="abc123", parent_shas=[]
            )
    assert files == mock_files
    # Initial commit: parent_sha should be the empty tree
    mock_get_changes.assert_called_once()
    call_args = mock_get_changes.call_args[0]
    assert call_args[1] == big_commit._GIT_EMPTY_TREE_SHA
    assert call_args[2] == "abc123"


def test_get_full_commit_files_raises_on_git_failure(tmp_path):
    """get_full_commit_files raises RuntimeError when git diff fails."""
    with patch(
        "github_activity_tracker.big_commit.ensure_repo_cloned",
        return_value=tmp_path,
    ):
        with patch(
            "github_activity_tracker.big_commit.get_commit_file_changes",
            side_effect=RuntimeError("empty tree not found"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                big_commit.get_full_commit_files(
                    "owner", "repo", commit_sha="abc123", parent_shas=[]
                )
    assert "abc123" in str(exc_info.value)
    assert "empty tree not found" in str(exc_info.value)
