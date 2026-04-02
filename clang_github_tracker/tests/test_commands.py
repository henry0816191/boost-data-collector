"""Tests for clang_github_tracker management commands."""

import logging
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

CMD_NAME = "run_clang_github_tracker"


@pytest.mark.django_db
def test_run_clang_github_tracker_dry_run_logs_resolved(caplog):
    """Dry run resolves dates from DB and does not call sync."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_clang_github_activity"
    ) as sync_mock:
        with caplog.at_level(logging.INFO):
            call_command(CMD_NAME, "--dry-run", stdout=StringIO(), stderr=StringIO())
    sync_mock.assert_not_called()
    assert any("Resolved:" in r.getMessage() for r in caplog.records)
    assert any("dry-run" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.django_db
def test_run_clang_github_tracker_skip_sync(caplog):
    """--skip-github-sync bypasses the GitHub sync step (not only under --dry-run)."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_clang_github_activity"
    ) as sync_mock, patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.write_md_files",
        return_value={},
    ):
        with caplog.at_level(logging.INFO):
            call_command(
                CMD_NAME,
                "--skip-github-sync",
                "--skip-pinecone",
                "--skip-remote-push",
                stdout=StringIO(),
                stderr=StringIO(),
            )
    sync_mock.assert_not_called()
    assert any("Resolved:" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_run_clang_github_tracker_since_until_aliases(caplog):
    """--from-date/--to-date aliases parse like Boost."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_clang_github_activity"
    ) as sync_mock:
        with caplog.at_level(logging.INFO):
            call_command(
                CMD_NAME,
                "--from-date=2024-01-01",
                "--to-date=2024-06-30",
                "--dry-run",
                stdout=StringIO(),
                stderr=StringIO(),
            )
    sync_mock.assert_not_called()
    assert any("Resolved:" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_run_clang_github_tracker_calls_sync_clang_github_activity_when_not_dry_run(
    caplog,
):
    """Without --dry-run, command calls sync_clang_github_activity with start_item."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_clang_github_activity",
        return_value=(0, [], []),
    ) as sync_mock:
        with caplog.at_level(logging.INFO):
            call_command(
                CMD_NAME,
                "--since=2024-01-01",
                "--until=2024-01-02",
                stdout=StringIO(),
                stderr=StringIO(),
            )
    sync_mock.assert_called_once()
    call_kw = sync_mock.call_args[1]
    assert "start_commit" in call_kw
    assert "start_item" in call_kw
    assert "end_date" in call_kw
    assert "start_issue" not in call_kw
    assert any("commits=" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_run_clang_github_tracker_skip_pinecone(caplog):
    """--skip-pinecone does not call run_cppa_pinecone_sync."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_clang_github_activity",
        return_value=(0, [1], []),
    ):
        with patch(
            "clang_github_tracker.management.commands.run_clang_github_tracker.call_command"
        ) as cc:
            with patch(
                "clang_github_tracker.management.commands.run_clang_github_tracker.write_md_files",
                return_value={},
            ):
                call_command(
                    CMD_NAME,
                    "--since=2024-01-01",
                    "--until=2024-01-02",
                    "--skip-pinecone",
                    "--skip-remote-push",
                    stdout=StringIO(),
                    stderr=StringIO(),
                )
    pinecone_calls = [
        c for c in cc.call_args_list if c[0] and c[0][0] == "run_cppa_pinecone_sync"
    ]
    assert not pinecone_calls


@pytest.mark.django_db
@override_settings(CLANG_GITHUB_PINECONE_APP_TYPE="")
def test_run_clang_github_tracker_empty_pinecone_app_type_skips_sync(caplog):
    """Empty CLANG_GITHUB_PINECONE_APP_TYPE must not call run_cppa_pinecone_sync with -issues/-prs."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_clang_github_activity",
        return_value=(0, [1], []),
    ):
        with patch(
            "clang_github_tracker.management.commands.run_clang_github_tracker.call_command"
        ) as cc:
            with patch(
                "clang_github_tracker.management.commands.run_clang_github_tracker.write_md_files",
                return_value={},
            ):
                with caplog.at_level(logging.WARNING):
                    call_command(
                        CMD_NAME,
                        "--since=2024-01-01",
                        "--until=2024-01-02",
                        "--skip-remote-push",
                        stdout=StringIO(),
                        stderr=StringIO(),
                    )
    pinecone_calls = [
        c for c in cc.call_args_list if c[0] and c[0][0] == "run_cppa_pinecone_sync"
    ]
    assert not pinecone_calls
    assert any(
        "CLANG_GITHUB_PINECONE_APP_TYPE is empty" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.django_db
@override_settings(
    CLANG_GITHUB_CONTEXT_REPO_OWNER="myorg",
    CLANG_GITHUB_CONTEXT_REPO_NAME="myrepo",
    CLANG_GITHUB_CONTEXT_REPO_BRANCH="main",
)
def test_push_markdown_calls_publish_and_unlinks_new_files(tmp_path):
    """_push_markdown invokes publish_clang_markdown then removes per-run md files."""
    md = tmp_path / "md_export"
    md.mkdir()
    f = md / "issues" / "2024" / "2024-01"
    f.mkdir(parents=True)
    one = f / "#1 - A.md"
    one.write_text("x", encoding="utf-8")
    new_files = {"issues/2024/2024-01/#1 - A.md": str(one)}

    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.publish_clang_markdown"
    ) as pub:
        from clang_github_tracker.management.commands.run_clang_github_tracker import (
            Command,
        )

        Command()._push_markdown(md, new_files)

    pub.assert_called_once_with(md, "myorg", "myrepo", "main", new_files)
    assert not one.exists()


@pytest.mark.django_db
@override_settings(
    CLANG_GITHUB_CONTEXT_REPO_OWNER="o",
    CLANG_GITHUB_CONTEXT_REPO_NAME="r",
    CLANG_GITHUB_CONTEXT_REPO_BRANCH="main",
)
def test_push_markdown_publish_failure_does_not_unlink(tmp_path):
    """Failed publish leaves local md files in place."""
    md = tmp_path / "md_export"
    md.mkdir()
    one = md / "x.md"
    one.write_text("keep", encoding="utf-8")
    new_files = {"x.md": str(one)}

    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.publish_clang_markdown",
        side_effect=CommandError("publish failed"),
    ):
        from clang_github_tracker.management.commands.run_clang_github_tracker import (
            Command,
        )

        with pytest.raises(CommandError, match="publish failed"):
            Command()._push_markdown(md, new_files)

    assert one.exists()
    assert one.read_text(encoding="utf-8") == "keep"
