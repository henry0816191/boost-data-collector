"""Tests for operations.md_ops.github_export rename and stale-path helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from operations.md_ops.github_export import (
    detect_renames,
    detect_renames_from_dirs,
    detect_stale_titled_paths,
)


def test_detect_renames_from_dirs_empty_new_files():
    """No new files means nothing to compare."""
    assert detect_renames_from_dirs("o", "r", "main", {}, token="t") == []


@patch("operations.md_ops.github_export.list_remote_directory")
def test_detect_renames_from_dirs_finds_old_title(mock_list_remote: MagicMock):
    """Remote dir lists old filename; new_files has new title for same #5."""
    mock_list_remote.return_value = [
        "issues/2024/2024-03/#5 - Old title.md",
    ]
    new_files = {
        "issues/2024/2024-03/#5 - New title.md": "/tmp/x",
    }
    out = detect_renames_from_dirs("own", "repo", "main", new_files, token="tok")
    assert out == ["issues/2024/2024-03/#5 - Old title.md"]
    mock_list_remote.assert_called()


@patch("operations.md_ops.github_export.list_remote_directory")
def test_detect_renames_from_dirs_no_conflict(mock_list_remote: MagicMock):
    """Remote only has the same filename as new_files."""
    mock_list_remote.return_value = [
        "issues/2024/2024-03/#5 - Same.md",
    ]
    new_files = {"issues/2024/2024-03/#5 - Same.md": "/tmp/x"}
    assert detect_renames_from_dirs("o", "r", "main", new_files, token="t") == []


@patch("operations.md_ops.github_export.list_remote_directory")
def test_detect_renames_from_dirs_non_numbered_md_ignored(
    mock_list_remote: MagicMock,
):
    """Files not matching #n - prefix are ignored."""
    mock_list_remote.return_value = ["issues/2024/2024-03/README.md"]
    new_files = {"issues/2024/2024-03/#5 - T.md": "/tmp/x"}
    assert detect_renames_from_dirs("o", "r", "main", new_files, token="t") == []


def test_detect_renames_success_matches_tree():
    """detect_renames uses same semantics as directory listing."""
    tree = [
        {"type": "blob", "path": "issues/2024/2024-03/#5 - Old title.md"},
    ]
    new_files = {"issues/2024/2024-03/#5 - New title.md": "/x"}
    assert detect_renames(tree, new_files) == ["issues/2024/2024-03/#5 - Old title.md"]


def test_detect_renames_empty_tree():
    assert detect_renames([], {"a/b.md": "/x"}) == []


def test_detect_stale_titled_paths_finds_old_file_on_disk(tmp_path: Path):
    """Local directory has old title; new_files points to new title."""
    d = tmp_path / "issues" / "2024" / "2024-03"
    d.mkdir(parents=True)
    old = d / "#5 - Old title.md"
    old.write_text("old", encoding="utf-8")
    new_files = {"issues/2024/2024-03/#5 - New title.md": str(d / "#5 - New title.md")}
    stale = detect_stale_titled_paths(tmp_path, new_files)
    assert stale == ["issues/2024/2024-03/#5 - Old title.md"]


def test_detect_stale_titled_paths_only_canonical(tmp_path: Path):
    """Only the new filename present → no stale paths."""
    d = tmp_path / "pull_requests" / "2024" / "2024-01"
    d.mkdir(parents=True)
    f = d / "#10 - Only.md"
    f.write_text("x", encoding="utf-8")
    new_files = {"pull_requests/2024/2024-01/#10 - Only.md": str(f)}
    assert detect_stale_titled_paths(tmp_path, new_files) == []


def test_detect_stale_titled_paths_missing_month_dir(tmp_path: Path):
    """Missing directory is treated as empty."""
    new_files = {"issues/2024/2024-99/#1 - A.md": "/nope"}
    assert detect_stale_titled_paths(tmp_path, new_files) == []


def test_detect_stale_titled_paths_empty_new_files(tmp_path: Path):
    assert detect_stale_titled_paths(tmp_path, {}) == []


def test_detect_stale_titled_paths_union_two_dirs(tmp_path: Path):
    """Multiple parent dirs each with stale file."""
    for sub, old_name in (
        ("issues/2024/2024-01", "#1 - Old.md"),
        ("issues/2024/2024-02", "#2 - Was.md"),
    ):
        p = tmp_path / sub
        p.mkdir(parents=True)
        (p / old_name).write_text("o", encoding="utf-8")
    new_files = {
        "issues/2024/2024-01/#1 - New.md": "/a",
        "issues/2024/2024-02/#2 - Now.md": "/b",
    }
    stale = set(detect_stale_titled_paths(tmp_path, new_files))
    assert stale == {
        "issues/2024/2024-01/#1 - Old.md",
        "issues/2024/2024-02/#2 - Was.md",
    }
