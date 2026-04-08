"""Tests for clang_github_tracker.publisher.publish_clang_markdown."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management.base import CommandError
from django.test import override_settings

from clang_github_tracker.publisher import publish_clang_markdown


@pytest.fixture
def raw_and_md(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    md = tmp_path / "md_export"
    md.mkdir()
    clone_root = raw / "clang_github_tracker" / "acme" / "priv"
    clone_root.mkdir(parents=True)
    (clone_root / ".git").mkdir()
    return raw, md, clone_root


def _author_settings(raw: Path):
    return override_settings(
        RAW_DIR=raw,
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.com",
    )


@pytest.mark.django_db
@patch("clang_github_tracker.publisher.git_push")
@patch("clang_github_tracker.publisher._reset_hard_to_upstream")
@patch("clang_github_tracker.publisher.pull")
@patch("clang_github_tracker.publisher.prepare_repo_for_pull")
@patch("clang_github_tracker.publisher.get_github_token", return_value="tok")
def test_publish_clang_markdown_success_copies_and_pushes(
    _token,
    _prepare,
    _pull,
    _reset,
    mock_push,
    raw_and_md,
):
    """Happy path: overlay md_export into clone and call git_push."""
    raw, md, clone_root = raw_and_md
    sub = md / "issues" / "2024" / "2024-01"
    sub.mkdir(parents=True)
    f = sub / "#1 - Title.md"
    f.write_text("body", encoding="utf-8")
    new_files = {"issues/2024/2024-01/#1 - Title.md": str(f)}
    with _author_settings(raw):
        publish_clang_markdown(md, "acme", "priv", "main", new_files)

    copied = clone_root / "issues" / "2024" / "2024-01" / "#1 - Title.md"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8") == "body"
    mock_push.assert_called_once()
    kwargs = mock_push.call_args[1]
    assert kwargs["branch"] == "main"
    assert kwargs["commit_message"] == "chore: update Clang issues/PRs markdown"


@pytest.mark.django_db
@patch("clang_github_tracker.publisher.git_push")
@patch("clang_github_tracker.publisher._reset_hard_to_upstream")
@patch("clang_github_tracker.publisher.pull")
@patch("clang_github_tracker.publisher.prepare_repo_for_pull")
@patch("clang_github_tracker.publisher.get_github_token", return_value="tok")
def test_publish_clang_markdown_stale_title_cleanup_md_then_clone(
    _token,
    _prepare,
    _pull,
    _reset,
    mock_push,
    raw_and_md,
):
    """Stale titled .md is removed from md_export (via new_files), then clone uses post-cleanup disk map."""
    raw, md, clone_root = raw_and_md
    sub = md / "issues" / "2024" / "2024-01"
    sub.mkdir(parents=True)
    new_path = sub / "#1 - New title.md"
    old_path = sub / "#1 - Old title.md"
    new_path.write_text("new", encoding="utf-8")
    old_path.write_text("old", encoding="utf-8")

    clone_sub = clone_root / "issues" / "2024" / "2024-01"
    clone_sub.mkdir(parents=True)
    (clone_sub / "#1 - Old title.md").write_text("stale on clone", encoding="utf-8")

    new_files = {"issues/2024/2024-01/#1 - New title.md": str(new_path)}
    with _author_settings(raw):
        publish_clang_markdown(md, "acme", "priv", "main", new_files)

    assert not old_path.is_file()
    assert new_path.is_file()
    copied = clone_sub / "#1 - New title.md"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8") == "new"
    assert not (clone_sub / "#1 - Old title.md").is_file()
    mock_push.assert_called_once()


@pytest.mark.django_db
@patch("clang_github_tracker.publisher.git_push")
@patch("clang_github_tracker.publisher._reset_hard_to_upstream")
@patch("clang_github_tracker.publisher.pull")
@patch("clang_github_tracker.publisher.prepare_repo_for_pull")
@patch("clang_github_tracker.publisher.get_github_token", return_value="tok")
def test_publish_clang_markdown_push_failure_raises_command_error(
    _token,
    _prepare,
    _pull,
    _reset,
    mock_push,
    raw_and_md,
):
    raw, md, _clone_root = raw_and_md
    err = subprocess.CalledProcessError(1, ["git", "push"])
    err.stderr = "rejected"
    err.stdout = ""
    mock_push.side_effect = err

    with _author_settings(raw):
        with pytest.raises(CommandError, match="Git push failed"):
            publish_clang_markdown(md, "acme", "priv", "main", {})


@pytest.mark.django_db
def test_publish_clang_markdown_invalid_owner(raw_and_md):
    raw, md, _ = raw_and_md
    with _author_settings(raw):
        with pytest.raises(CommandError, match="Invalid GitHub owner"):
            publish_clang_markdown(md, "evil/org", "priv", "main", {})


@pytest.mark.django_db
def test_publish_clang_markdown_overlap_errors(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    clone = raw / "clang_github_tracker" / "acme" / "priv"
    clone.mkdir(parents=True)
    (clone / ".git").mkdir()
    with _author_settings(raw):
        with pytest.raises(CommandError, match="must not overlap"):
            publish_clang_markdown(clone, "acme", "priv", "main", {})


@pytest.mark.django_db
@patch("clang_github_tracker.publisher.git_push")
@patch("clang_github_tracker.publisher._reset_hard_to_upstream")
@patch("clang_github_tracker.publisher.pull")
@patch("clang_github_tracker.publisher.prepare_repo_for_pull")
@patch("clang_github_tracker.publisher.clone_repo")
@patch("clang_github_tracker.publisher.get_github_token", return_value="tok")
def test_publish_clang_markdown_clones_when_no_git_dir(
    _token,
    mock_clone,
    _prepare,
    _pull,
    _reset,
    mock_push,
    tmp_path: Path,
):
    """Missing .git triggers clone_repo; mock creates minimal repo after rmtree."""
    raw = tmp_path / "raw"
    raw.mkdir()
    md = tmp_path / "md"
    md.mkdir()
    clone = raw / "clang_github_tracker" / "acme" / "priv"
    clone.mkdir(parents=True)

    def _clone_side_effect(_slug, dest, **_kw):
        dest = Path(dest)
        if dest.exists():
            import shutil

            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        (dest / ".git").mkdir()

    mock_clone.side_effect = _clone_side_effect

    with _author_settings(raw):
        publish_clang_markdown(md, "acme", "priv", "main", {})
    mock_clone.assert_called_once()
