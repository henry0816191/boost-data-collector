"""Tests for boost_collector_runner.schedule_config: load_config and _validate_task validation."""

import pytest
import yaml

from boost_collector_runner.schedule_config import (
    INTERVAL_MINUTES_MAX,
    load_config,
    _validate_task,
)


# --- load_config validation ---


def test_load_config_requires_path():
    """load_config(path=None) raises ValueError."""
    with pytest.raises(ValueError, match="load_config requires a path"):
        load_config(None)


def test_load_config_file_not_found(tmp_path):
    """load_config with non-existent path raises FileNotFoundError."""
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="Schedule YAML not found"):
        load_config(missing)


def test_load_config_data_not_dict(tmp_path):
    """YAML that is not a dict (e.g. list or null) raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Schedule YAML must be a dict with 'groups'"):
        load_config(path)

    path.write_text("null", encoding="utf-8")
    with pytest.raises(ValueError, match="Schedule YAML must be a dict with 'groups'"):
        load_config(path)


def test_load_config_groups_missing(tmp_path):
    """YAML without 'groups' key or with null groups raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"other": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="Schedule YAML must have 'groups' \\(dict\\)"):
        load_config(path)

    path.write_text(yaml.dump({"groups": None}), encoding="utf-8")
    with pytest.raises(ValueError, match="Schedule YAML must have 'groups' \\(dict\\)"):
        load_config(path)


def test_load_config_groups_not_dict(tmp_path):
    """YAML with groups as non-dict raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"groups": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="Schedule YAML must have 'groups' \\(dict\\)"):
        load_config(path)


def test_load_config_group_id_empty_string(tmp_path):
    """Group id that is empty string raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "": {
                        "default_time": "04:10",
                        "tasks": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Group id must be a non-empty string"):
        load_config(path)


def test_load_config_group_id_whitespace_only(tmp_path):
    """Group id that is only whitespace raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "   ": {
                        "default_time": "04:10",
                        "tasks": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Group id must be a non-empty string"):
        load_config(path)


def test_load_config_group_data_not_dict(tmp_path):
    """Group value that is not a dict raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": "not a dict",
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Group 'github' must be a dict"):
        load_config(path)


def test_load_config_default_time_missing(tmp_path):
    """Group without default_time or with empty default_time raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "tasks": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must have 'default_time'"):
        load_config(path)

    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "   ",
                        "tasks": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must have 'default_time'"):
        load_config(path)


def test_load_config_default_time_invalid(tmp_path):
    """Group with invalid default_time format raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "25:00",
                        "tasks": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid time"):
        load_config(path)

    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "not-time",
                        "tasks": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid time"):
        load_config(path)


def test_load_config_tasks_not_list(tmp_path):
    """Group with tasks not a list raises ValueError."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "04:10",
                        "tasks": "not a list",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must have 'tasks' \\(list\\)"):
        load_config(path)


def test_load_config_valid_minimal(tmp_path):
    """Valid minimal YAML loads and returns data dict."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "04:10",
                        "tasks": [
                            {"command": "run_foo", "schedule": "daily"},
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    data = load_config(path)
    assert data is not None
    assert "groups" in data
    assert "github" in data["groups"]
    assert data["groups"]["github"]["default_time"] == "04:10"


def test_load_config_invalid_task_fails(tmp_path):
    """Invalid task in YAML causes load_config to raise ValueError from _validate_task."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "groups": {
                    "github": {
                        "default_time": "04:10",
                        "tasks": [
                            {"command": "run_foo", "schedule": "daily"},
                            {"command": "run_bar"},  # missing schedule
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="'schedule' must be one of"):
        load_config(path)


# --- _validate_task validation ---


def test_validate_task_not_dict():
    """Task that is not a dict raises ValueError."""
    with pytest.raises(ValueError, match="Task in group .* must be a dict"):
        _validate_task([], "g1")
    with pytest.raises(ValueError, match="Task in group .* must be a dict"):
        _validate_task("task", "g1")


def test_validate_task_command_missing():
    """Task without command or with empty command raises ValueError."""
    with pytest.raises(ValueError, match=r"must have 'command' \(non-empty string\)"):
        _validate_task({"schedule": "daily"}, "g1")
    with pytest.raises(ValueError, match=r"must have 'command' \(non-empty string\)"):
        _validate_task({"command": "", "schedule": "daily"}, "g1")
    with pytest.raises(ValueError, match=r"must have 'command' \(non-empty string\)"):
        _validate_task({"command": 123, "schedule": "daily"}, "g1")


def test_validate_task_schedule_invalid():
    """Task with missing or invalid schedule raises ValueError."""
    with pytest.raises(ValueError, match="'schedule' must be one of"):
        _validate_task({"command": "c1", "schedule": "invalid"}, "g1")
    with pytest.raises(ValueError, match="'schedule' must be one of"):
        _validate_task({"command": "c1"}, "g1")


def test_validate_task_weekly_requires_on():
    """Task with schedule weekly but no valid on/day_of_week raises ValueError."""
    with pytest.raises(ValueError, match="'schedule: weekly' requires 'on'"):
        _validate_task({"command": "c1", "schedule": "weekly"}, "g1")
    with pytest.raises(ValueError, match="'schedule: weekly' requires 'on'"):
        _validate_task({"command": "c1", "schedule": "weekly", "on": "notaday"}, "g1")


def test_validate_task_weekly_valid():
    """Task with schedule weekly and valid on passes."""
    _validate_task({"command": "c1", "schedule": "weekly", "on": "monday"}, "g1")
    _validate_task({"command": "c1", "schedule": "weekly", "on": "mon"}, "g1")


def test_validate_task_monthly_requires_on():
    """Task with schedule monthly but no on raises ValueError."""
    with pytest.raises(ValueError, match="'schedule: monthly' requires 'on'"):
        _validate_task({"command": "c1", "schedule": "monthly"}, "g1")


def test_validate_task_monthly_on_non_numeric():
    """Task with schedule monthly and on not convertible to int raises ValueError."""
    with pytest.raises(ValueError, match="'schedule: monthly' requires 'on' \\(1-31"):
        _validate_task({"command": "c1", "schedule": "monthly", "on": "abc"}, "g1")


def test_validate_task_monthly_on_out_of_range():
    """Task with schedule monthly and on outside 1-31 raises ValueError."""
    with pytest.raises(ValueError, match="'schedule: monthly' requires 'on' \\(1-31"):
        _validate_task({"command": "c1", "schedule": "monthly", "on": 0}, "g1")
    with pytest.raises(ValueError, match="'schedule: monthly' requires 'on' \\(1-31"):
        _validate_task({"command": "c1", "schedule": "monthly", "on": 32}, "g1")


def test_validate_task_monthly_valid():
    """Task with schedule monthly and valid on (1-31) passes."""
    _validate_task({"command": "c1", "schedule": "monthly", "on": 1}, "g1")
    _validate_task({"command": "c1", "schedule": "monthly", "on": "15"}, "g1")
    _validate_task({"command": "c1", "schedule": "monthly", "on": 31}, "g1")


def test_validate_task_interval_requires_minutes():
    """Task with schedule interval but no minutes raises ValueError."""
    with pytest.raises(ValueError, match="'schedule: interval' requires 'minutes'"):
        _validate_task({"command": "c1", "schedule": "interval"}, "g1")


def test_validate_task_interval_minutes_not_int():
    """Task with schedule interval and minutes not int raises ValueError."""
    with pytest.raises(ValueError, match="'minutes' must be an integer"):
        _validate_task({"command": "c1", "schedule": "interval", "minutes": "x"}, "g1")


def test_validate_task_interval_minutes_out_of_range():
    """Task with schedule interval and minutes outside 1-180 raises ValueError."""
    with pytest.raises(ValueError, match="'minutes' must be 1-180"):
        _validate_task({"command": "c1", "schedule": "interval", "minutes": 0}, "g1")
    with pytest.raises(ValueError, match="'minutes' must be 1-180"):
        _validate_task(
            {
                "command": "c1",
                "schedule": "interval",
                "minutes": INTERVAL_MINUTES_MAX + 1,
            },
            "g1",
        )


def test_validate_task_interval_valid():
    """Task with schedule interval and valid minutes passes."""
    _validate_task({"command": "c1", "schedule": "interval", "minutes": 1}, "g1")
    _validate_task({"command": "c1", "schedule": "interval", "minutes": 60}, "g1")
    _validate_task(
        {"command": "c1", "schedule": "interval", "minutes": INTERVAL_MINUTES_MAX}, "g1"
    )


def test_validate_task_enabled_not_bool():
    """Task with enabled not boolean raises ValueError."""
    with pytest.raises(ValueError, match="'enabled' must be boolean"):
        _validate_task(
            {"command": "c1", "schedule": "daily", "enabled": "yes"},
            "g1",
        )


def test_validate_task_args_not_list():
    """Task with args not a list raises ValueError."""
    with pytest.raises(ValueError, match="'args' must be a list of strings"):
        _validate_task(
            {"command": "c1", "schedule": "daily", "args": "not-a-list"},
            "g1",
        )


def test_validate_task_args_element_not_string():
    """Task with args containing non-string element raises ValueError."""
    with pytest.raises(ValueError, match=r"'args\[0\]' must be a string"):
        _validate_task(
            {"command": "c1", "schedule": "daily", "args": [123]},
            "g1",
        )
    with pytest.raises(ValueError, match=r"'args\[1\]' must be a string"):
        _validate_task(
            {"command": "c1", "schedule": "daily", "args": ["--ok", None]},
            "g1",
        )


def test_validate_task_args_valid():
    """Task with args as list of strings passes."""
    _validate_task(
        {"command": "c1", "schedule": "daily", "args": ["--a", "b"]},
        "g1",
    )


def test_validate_task_daily_valid():
    """Minimal valid daily task passes."""
    _validate_task({"command": "c1", "schedule": "daily"}, "g1")


def test_validate_task_on_release_valid():
    """Minimal valid on_release task passes."""
    _validate_task({"command": "c1", "schedule": "on_release"}, "g1")
