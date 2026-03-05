"""Tests for boost_collector_runner management commands."""

import pytest
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, get_commands
from django.core.management.base import CommandError


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
                                "command": "run_boost_library_tracker",
                                "schedule": "daily",
                            },
                        ],
                    },
                },
            }
        ),
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
            "--schedule",
            "daily",
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
