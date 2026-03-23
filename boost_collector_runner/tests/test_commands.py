"""Tests for boost_collector_runner management commands."""

import pytest
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, get_commands
from django.core.management.base import CommandError

from boost_collector_runner.schedule_config import DEFAULT_GROUP_BATCH_SCHEDULE_KIND


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
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "04:10",
                        "tasks": [
                            {
                                "command": "run_boost_github_activity_tracker",
                                "schedule": "daily",
                            },
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    settings.BOOST_COLLECTOR_SCHEDULE_YAML = str(yaml_path)

    out = StringIO()
    err = StringIO()
    with patch(
        "boost_collector_runner.schedule_config._get_yaml_path",
        return_value=yaml_path,
    ), patch(
        "boost_collector_runner.management.commands.run_scheduled_collectors.call_command",
        return_value=None,
    ) as mock_call:
        call_command(
            "run_scheduled_collectors",
            "--schedule",
            "daily",
            stdout=out,
            stderr=err,
        )
    # Command uses logger, not stdout; verify it ran the task from YAML
    assert mock_call.call_count == 1
    mock_call.assert_called_once_with("run_boost_github_activity_tracker")


@pytest.mark.django_db
def test_run_scheduled_collectors_default_group_batch(tmp_path, settings):
    """run_scheduled_collectors --schedule default --group X runs group batch (daily + weekly + monthly + on_release) for that group."""
    import yaml

    yaml_path = tmp_path / "boost_collector_schedule.yaml"
    yaml_path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "04:10",
                        "tasks": [
                            {"command": "run_foo", "schedule": "daily"},
                            {
                                "command": "run_bar",
                                "schedule": "weekly",
                                "on": "monday",
                            },
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    settings.BOOST_COLLECTOR_SCHEDULE_YAML = str(yaml_path)

    out = StringIO()
    err = StringIO()
    with patch(
        "boost_collector_runner.schedule_config._get_yaml_path",
        return_value=yaml_path,
    ), patch(
        "boost_collector_runner.management.commands.run_scheduled_collectors.call_command",
        return_value=None,
    ) as mock_call:
        call_command(
            "run_scheduled_collectors",
            "--schedule",
            DEFAULT_GROUP_BATCH_SCHEDULE_KIND,
            "--group",
            "github",
            stdout=out,
            stderr=err,
        )
    # Command uses logger, not stdout; verify it ran the group batch tasks
    assert mock_call.call_count >= 1
    call_names = [c[0][0] for c in mock_call.call_args_list]
    assert "run_foo" in call_names or "run_bar" in call_names


@pytest.mark.django_db
def test_run_scheduled_collectors_requires_schedule():
    """run_scheduled_collectors without --schedule raises CommandError."""
    out = StringIO()
    err = StringIO()
    with pytest.raises(CommandError) as exc_info:
        call_command("run_scheduled_collectors", stdout=out, stderr=err)
    assert "schedule" in str(exc_info.value).lower()
