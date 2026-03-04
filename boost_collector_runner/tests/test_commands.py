"""Tests for boost_collector_runner management commands."""

import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

from django.core.management import call_command, get_commands
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_run_collectors_command_exists(boost_collector_runner_cmd_name):
    """run_collectors is registered and runnable; sub-commands are mocked."""
    commands = get_commands()
    assert (
        boost_collector_runner_cmd_name in commands
    ), f"Command {boost_collector_runner_cmd_name!r} should be registered"

    out = StringIO()
    err = StringIO()
    with patch(
        "boost_collector_runner.management.commands.run_collectors.call_command",
        return_value=None,
    ):
        call_command(boost_collector_runner_cmd_name, stdout=out, stderr=err)
    content = out.getvalue()
    assert "Running" in content and "succeeded" in content


@pytest.mark.django_db
def test_run_collectors_success_when_all_succeed(boost_collector_runner_cmd_name):
    """When all sub-commands succeed, run_collectors exits 0 and writes success summary."""
    out = StringIO()
    err = StringIO()
    with patch(
        "boost_collector_runner.management.commands.run_collectors.call_command",
        return_value=None,
    ):
        call_command(boost_collector_runner_cmd_name, stdout=out, stderr=err)
    content = out.getvalue()
    assert "succeeded" in content and "failed" in content
    assert "success" in content.lower()


@pytest.mark.django_db
def test_run_collectors_exits_nonzero_on_command_error(boost_collector_runner_cmd_name):
    """When a sub-command raises CommandError, run_collectors exits with non-zero."""
    out = StringIO()
    err = StringIO()
    with patch(
        "boost_collector_runner.management.commands.run_collectors.call_command",
        side_effect=CommandError("sub-command failed"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            call_command(boost_collector_runner_cmd_name, stdout=out, stderr=err)
    assert exc_info.value.code != 0


@pytest.mark.django_db
def test_run_collectors_stop_on_failure(boost_collector_runner_cmd_name):
    """With --stop-on-failure, only one sub-command is run when the first fails."""
    out = StringIO()
    err = StringIO()
    call_command_mock = MagicMock(side_effect=CommandError("first failed"))
    with patch(
        "boost_collector_runner.management.commands.run_collectors.call_command",
        call_command_mock,
    ):
        with pytest.raises(SystemExit):
            call_command(
                boost_collector_runner_cmd_name,
                "--stop-on-failure",
                stdout=out,
                stderr=err,
            )
    assert call_command_mock.call_count == 1


@pytest.mark.django_db
def test_run_scheduled_collectors_command_exists():
    """run_scheduled_collectors is registered."""
    commands = get_commands()
    assert "run_scheduled_collectors" in commands


@pytest.mark.django_db
def test_run_scheduled_collectors_daily_runs_tasks_from_yaml(tmp_path, settings):
    """run_scheduled_collectors --schedule daily runs tasks returned by get_tasks_for_schedule."""
    import yaml

    yaml_path = tmp_path / "boost_collector_schedule.yaml"
    yaml_path.write_text(
        yaml.dump({
            "groups": {
                "github": {
                    "default_time": "04:10",
                    "tasks": [
                        {"command": "run_boost_library_tracker", "schedule": "daily"},
                    ],
                },
            },
        }),
        encoding="utf-8",
    )
    settings.BOOST_COLLECTOR_SCHEDULE_YAML = yaml_path

    out = StringIO()
    err = StringIO()
    with patch(
        "boost_collector_runner.management.commands.run_scheduled_collectors.call_command",
        return_value=None,
    ):
        call_command(
            "run_scheduled_collectors",
            "--schedule", "daily",
            stdout=out,
            stderr=err,
        )
    content = out.getvalue()
    assert "Running" in content and "run_boost_library_tracker" in content
    assert "succeeded" in content


@pytest.mark.django_db
def test_run_scheduled_collectors_requires_schedule():
    """run_scheduled_collectors without --schedule raises CommandError."""
    from django.core.management import call_command

    out = StringIO()
    err = StringIO()
    with pytest.raises(CommandError) as exc_info:
        call_command("run_scheduled_collectors", stdout=out, stderr=err)
    assert "schedule" in str(exc_info.value).lower()
