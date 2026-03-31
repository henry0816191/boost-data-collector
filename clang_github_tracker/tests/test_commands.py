"""Tests for clang_github_tracker management commands."""

import logging

import pytest
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command

CMD_NAME = "run_clang_github_tracker"


@pytest.mark.django_db
def test_run_clang_github_tracker_dry_run_logs_resolved(caplog):
    """Dry run resolves dates from DB and does not call sync."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_raw_only"
    ) as sync_mock:
        with caplog.at_level(logging.INFO):
            call_command(CMD_NAME, "--dry-run", stdout=StringIO(), stderr=StringIO())
    sync_mock.assert_not_called()
    assert any("Resolved:" in r.getMessage() for r in caplog.records)
    assert any("dry-run" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.django_db
def test_run_clang_github_tracker_dry_run_skip_sync(caplog):
    """Dry run with --skip-github-sync still logs resolved window."""
    with caplog.at_level(logging.INFO):
        call_command(
            CMD_NAME,
            "--dry-run",
            "--skip-github-sync",
            stdout=StringIO(),
            stderr=StringIO(),
        )
    assert any("Resolved:" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_run_clang_github_tracker_since_until_aliases(caplog):
    """--from-date/--to-date aliases parse like Boost."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_raw_only"
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
def test_run_clang_github_tracker_calls_sync_raw_only_when_not_dry_run(caplog):
    """Without --dry-run, command calls sync_raw_only with start_item."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_raw_only",
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
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_raw_only",
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
        c
        for c in cc.call_args_list
        if c[0] and c[0][0] == "run_cppa_pinecone_sync"
    ]
    assert not pinecone_calls
