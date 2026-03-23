"""Tests for clang_github_tracker management command (run_clang_github_tracker)."""

import json
import logging

import pytest
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command

from config.workspace import get_workspace_path

CMD_NAME = "run_clang_github_tracker"


@pytest.mark.django_db
def test_run_clang_github_tracker_dry_run_creates_state_if_missing(caplog):
    """With --dry-run and no state file, command creates state from raw scan and resolves dates."""
    workspace = get_workspace_path("clang_github_activity")
    state_file = workspace / "state.json"
    if state_file.exists():
        state_file.unlink()
    with caplog.at_level(logging.INFO):
        call_command(CMD_NAME, "--dry-run", stdout=StringIO(), stderr=StringIO())
    assert state_file.exists(), "State file should be created by command"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "last_commit_date" in state
    assert "last_issue_date" in state
    assert "last_pr_date" in state
    assert any("Resolved:" in r.getMessage() for r in caplog.records)
    assert any("Dry run" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_run_clang_github_tracker_dry_run_with_dates(caplog):
    """With --from-date and --to-date and --dry-run, command does not call sync."""
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
    """Without --dry-run, command calls sync_raw_only with resolved dates."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_raw_only",
        return_value=(0, [], []),  # commits_saved, issue_numbers, pr_numbers (lists)
    ) as sync_mock:
        with caplog.at_level(logging.INFO):
            call_command(
                CMD_NAME,
                "--from-date=2024-01-01",
                "--to-date=2024-01-02",
                stdout=StringIO(),
                stderr=StringIO(),
            )
        sync_mock.assert_called_once()
        call_kw = sync_mock.call_args[1]
        assert "start_commit" in call_kw
        assert "end_date" in call_kw
        assert any("saved commits=" in r.getMessage() for r in caplog.records)
