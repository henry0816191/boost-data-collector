"""Tests for boost_library_tracker management commands (run_boost_library_tracker)."""

import pytest
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command


CMD_NAME = "run_boost_library_tracker"


@pytest.mark.django_db
def test_run_boost_library_tracker_invalid_from_date_warns_and_continues_with_none():
    """With invalid --from-date, command proceeds and passes start_date=None to task (downstream None handling)."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (b"", "utf-8")
    mock_account = MagicMock()
    mock_account.username = "boostorg"
    with patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_github_client",
        return_value=mock_client,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_or_create_owner_account",
        return_value=mock_account,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.sync_github",
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.task_fetch_github_activity",
    ) as task_mock:
        call_command(
            CMD_NAME,
            "--from-date=not-a-date",
            "--task=github_activity",
            "--dry-run",
            stdout=StringIO(),
            stderr=StringIO(),
        )
    task_mock.assert_called_once()
    kwargs = task_mock.call_args[1]
    assert "start_date" in kwargs
    assert kwargs["start_date"] is None


@pytest.mark.django_db
def test_run_boost_library_tracker_invalid_to_date_warns_and_continues_with_none():
    """With invalid --to-date, command proceeds and passes end_date=None to task (downstream None handling)."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (b"", "utf-8")
    mock_account = MagicMock()
    mock_account.username = "boostorg"
    with patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_github_client",
        return_value=mock_client,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_or_create_owner_account",
        return_value=mock_account,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.sync_github",
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.task_fetch_github_activity",
    ) as task_mock:
        call_command(
            CMD_NAME,
            "--to-date=invalid",
            "--task=github_activity",
            "--dry-run",
            stdout=StringIO(),
            stderr=StringIO(),
        )
    task_mock.assert_called_once()
    kwargs = task_mock.call_args[1]
    assert "end_date" in kwargs
    assert kwargs["end_date"] is None


@pytest.mark.django_db
def test_run_boost_library_tracker_from_library_not_found_warns_and_starts_from_first(
    caplog,
):
    """With --from-library not in repo list, command logs warning and starts from first (idx=0)."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (
        b'[submodule "libs/build"]\npath = libs/build\nurl = ../build.git\n',
        "utf-8",
    )
    mock_account = MagicMock()
    mock_account.username = "boostorg"
    with patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_github_client",
        return_value=mock_client,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_or_create_owner_account",
        return_value=mock_account,
    ):
        call_command(
            CMD_NAME,
            "--from-library=NonExistentLib",
            "--task=github_activity",
            "--dry-run",
            stdout=StringIO(),
            stderr=StringIO(),
        )
    assert any(
        "NonExistentLib" in r.getMessage()
        and "starting from first" in r.getMessage().lower()
        for r in caplog.records
        if r.levelname == "WARNING"
    )


@pytest.mark.django_db
def test_run_boost_library_tracker_from_library_valid_calls_sync_with_filter():
    """With valid --from-library and --dry-run, task runs and stdout mentions the library."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (
        b'[submodule "libs/build"]\npath = libs/build\nurl = ../build.git\n'
        b'[submodule "libs/algorithm"]\npath = libs/algorithm\nurl = ../algorithm.git\n',
        "utf-8",
    )
    mock_account = MagicMock()
    mock_account.username = "boostorg"
    with patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_github_client",
        return_value=mock_client,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_or_create_owner_account",
        return_value=mock_account,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.sync_github",
    ):
        out = StringIO()
        err = StringIO()
        call_command(
            CMD_NAME,
            "--from-library=algorithm",
            "--task=github_activity",
            "--dry-run",
            stdout=out,
            stderr=err,
        )
    content = out.getvalue()
    assert "algorithm" in content.lower() or "Starting from" in content


@pytest.mark.django_db
def test_run_boost_library_tracker_passes_from_date_to_date_to_task():
    """With --from-date and --to-date, task_fetch_github_activity is called with those dates."""
    mock_client = MagicMock()
    mock_client.get_file_content.return_value = (b"", "utf-8")
    mock_account = MagicMock()
    mock_account.username = "boostorg"
    with patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_github_client",
        return_value=mock_client,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.get_or_create_owner_account",
        return_value=mock_account,
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.sync_github",
    ), patch(
        "boost_library_tracker.management.commands.run_boost_library_tracker.task_fetch_github_activity",
    ) as task_mock:
        out = StringIO()
        call_command(
            CMD_NAME,
            "--from-date=2024-01-01",
            "--to-date=2024-06-30",
            "--task=github_activity",
            "--dry-run",
            stdout=out,
            stderr=StringIO(),
        )
        task_mock.assert_called_once()
        call_kw = task_mock.call_args[1]
        assert "start_date" in call_kw
        assert "end_date" in call_kw
        assert call_kw["start_date"] is not None
        assert call_kw["end_date"] is not None
        assert call_kw["start_date"].isoformat().startswith("2024-01-01")
        assert call_kw["end_date"].isoformat().startswith("2024-06-30")
