"""Tests for clang_github_tracker management command (run_clang_github_tracker)."""

import pytest
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command

from config.workspace import get_workspace_path

CMD_NAME = "run_clang_github_tracker"


@pytest.mark.django_db
def test_run_clang_github_tracker_dry_run_creates_state_if_missing():
    """With --dry-run and no state file, command creates state from raw scan and resolves dates."""
    workspace = get_workspace_path("clang_github_activity")
    state_file = workspace / "state.json"
    if state_file.exists():
        state_file.unlink()
    out = StringIO()
    call_command(
        CMD_NAME,
        "--dry-run",
        stdout=out,
        stderr=StringIO(),
    )
    content = out.getvalue()
    assert "Resolved:" in content
    assert "Dry run" in content


@pytest.mark.django_db
def test_run_clang_github_tracker_dry_run_with_dates():
    """With --from-date and --to-date and --dry-run, command does not call sync."""
    with patch("clang_github_tracker.management.commands.run_clang_github_tracker.sync_raw_only") as sync_mock:
        out = StringIO()
        call_command(
            CMD_NAME,
            "--from-date=2024-01-01",
            "--to-date=2024-06-30",
            "--dry-run",
            stdout=out,
            stderr=StringIO(),
        )
        sync_mock.assert_not_called()
        assert "Resolved:" in out.getvalue()


@pytest.mark.django_db
def test_run_clang_github_tracker_calls_sync_raw_only_when_not_dry_run():
    """Without --dry-run, command calls sync_raw_only with resolved dates."""
    with patch(
        "clang_github_tracker.management.commands.run_clang_github_tracker.sync_raw_only",
        return_value=(0, 0, 0),
    ) as sync_mock:
        out = StringIO()
        call_command(
            CMD_NAME,
            "--from-date=2024-01-01",
            "--to-date=2024-01-02",
            stdout=out,
            stderr=StringIO(),
        )
        sync_mock.assert_called_once()
        call_kw = sync_mock.call_args[1]
        assert "start_commit" in call_kw
        assert "end_date" in call_kw
        assert "saved commits=0" in out.getvalue()
