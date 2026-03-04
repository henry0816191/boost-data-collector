"""
Load and validate boost collector schedule YAML; expose groups/tasks and Celery Beat schedule.
Config file: config/boost_collector_schedule.yaml (see docs/Workflow.md).

Execution model: Tasks within a group run sequentially. Each group has one Beat entry (at the
group's default_time); when it runs, all non-interval tasks in that group run together: daily,
weekly (if today matches), monthly (if today matches), and on_release (if a new Boost release
exists). So no two distinct tasks in the same group run in separate batches (except interval
tasks, which run in separate Beat entries and are independent). Interval tasks are not part of
a group run; they get separate Beat entries and run independently.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SCHEDULE_TYPES = ("daily", "weekly", "monthly", "on_release", "interval")
# Interval schedule: minutes only; max 3 hours (use for short periodic runs, e.g. every 15 min).
INTERVAL_MINUTES_MAX = 180
DAY_OF_WEEK_FULL = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 0,
}
DAY_ABBREV_TO_FULL = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
}
DEFAULT_TIME = "04:10"


def _normalize_day_of_week(val):
    """Return full day name (e.g. 'monday') from 'monday', 'mon', etc."""
    if not val:
        return None
    s = str(val).strip().lower()
    if s in DAY_OF_WEEK_FULL:
        return s
    if s in DAY_ABBREV_TO_FULL:
        return DAY_ABBREV_TO_FULL[s]
    return None


def _get_yaml_path():
    from django.conf import settings

    path = getattr(settings, "BOOST_COLLECTOR_SCHEDULE_YAML", None)
    if path is None:
        path = Path(settings.BASE_DIR) / "config" / "boost_collector_schedule.yaml"
    return Path(path)


def _parse_time(s):
    """Parse 'HH:MM' -> (hour, minute)."""
    parts = str(s).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time {s!r}; use HH:MM")
    h, m = int(parts[0], 10), int(parts[1], 10)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid time {s!r}")
    return h, m


def _normalize_task(task, group_id, group_default_time):
    """Build a normalized task dict; default enabled=True; time is always the group's default_time (tasks do not have their own time)."""
    t = dict(task)
    t.setdefault("enabled", True)
    if t.get("enabled") is False:
        return t
    t["time"] = group_default_time
    t["_group_id"] = group_id

    schedule = t.get("schedule")
    if schedule == "weekly":
        on_val = t.get("on") or t.get("day_of_week")
        full = _normalize_day_of_week(on_val)
        if full:
            t["day_of_week"] = full
    elif schedule == "monthly":
        on_val = t.get("on") if "on" in t else t.get("day_of_month")
        if on_val is not None:
            t["day_of_month"] = int(on_val)
    elif schedule == "interval":
        m = t.get("minutes")
        if m is not None:
            t["minutes"] = int(m)

    if "args" in t and not isinstance(t["args"], list):
        raise ValueError(f"Task {t.get('command')!r}: 'args' must be a list of strings")
    # Each element = one CLI token (e.g. ['--sync-message', '--from-library', 'asio'])
    if "args" in t:
        for i, a in enumerate(t["args"]):
            if not isinstance(a, str):
                raise ValueError(
                    f"Task {t.get('command')!r}: 'args[{i}]' must be a string"
                )
    return t


def _validate_task(task, group_id):
    """Validate a single task; raise ValueError on error."""
    if not isinstance(task, dict):
        raise ValueError(f"Task in group {group_id!r} must be a dict")
    command = task.get("command")
    if not command or not isinstance(command, str):
        raise ValueError(
            f"Task in group {group_id!r} must have 'command' (non-empty string)"
        )
    schedule = task.get("schedule")
    if schedule not in SCHEDULE_TYPES:
        raise ValueError(
            f"Task {command!r} in group {group_id!r}: "
            f"'schedule' must be one of {SCHEDULE_TYPES}"
        )
    if schedule == "weekly":
        on_val = task.get("on") or task.get("day_of_week")
        if not _normalize_day_of_week(on_val):
            raise ValueError(
                f"Task {command!r} in group {group_id!r}: "
                f"'schedule: weekly' requires 'on' (e.g. monday or mon)"
            )
    if schedule == "monthly":
        on_val = task.get("on") if "on" in task else task.get("day_of_month")
        if on_val is None or not (1 <= int(on_val) <= 31):
            raise ValueError(
                f"Task {command!r} in group {group_id!r}: "
                f"'schedule: monthly' requires 'on' (1-31, day of month)"
            )
    if schedule == "interval":
        m = task.get("minutes")
        if m is None:
            raise ValueError(
                f"Task {command!r} in group {group_id!r}: "
                f"'schedule: interval' requires 'minutes' (1-{INTERVAL_MINUTES_MAX})"
            )
        try:
            m_int = int(m)
        except (TypeError, ValueError):
            raise ValueError(
                f"Task {command!r} in group {group_id!r}: 'minutes' must be an integer"
            ) from None
        if not (1 <= m_int <= INTERVAL_MINUTES_MAX):
            raise ValueError(
                f"Task {command!r} in group {group_id!r}: "
                f"'minutes' must be 1-{INTERVAL_MINUTES_MAX} (at most 3 hours)"
            )
    if "enabled" in task and not isinstance(task["enabled"], bool):
        raise ValueError(
            f"Task {command!r} in group {group_id!r}: 'enabled' must be boolean"
        )


def load_config(path=None):
    """Load and validate YAML; return raw config dict. Raises FileNotFoundError, ValueError, yaml.YAMLError.
    path is required; raises ValueError if not given.
    """
    if path is None:
        raise ValueError("load_config requires a path; pass the YAML file path.")
    else:
        path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Schedule YAML not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or not isinstance(data, dict):
        raise ValueError("Schedule YAML must be a dict with 'groups'")
    groups = data.get("groups")
    if not groups or not isinstance(groups, dict):
        raise ValueError("Schedule YAML must have 'groups' (dict)")

    for group_id, group_data in groups.items():
        if not isinstance(group_data, dict):
            raise ValueError(f"Group {group_id!r} must be a dict")
        group_time = (group_data.get("default_time") or "").strip()
        if not group_time:
            raise ValueError(f"Group {group_id!r} must have 'default_time' (e.g. \"04:10\")")
        _parse_time(group_time)  # validate format; return value unused
        tasks = group_data.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError(f"Group {group_id!r} must have 'tasks' (list)")
        for task in tasks:
            _validate_task(task, group_id)

    return data


def get_groups_and_tasks(data=None):
    """
    Return ordered list of (group_id, list of task dicts).
    Task dicts have: command, schedule, time (from group default_time), on/day_of_week/day_of_month (if applicable), enabled, args.
    Only includes tasks that are enabled (enabled is not False).
    Time comes from each group's default_time (required per group); tasks do not have their own time.
    If data is provided (e.g. from load_config), it is used and the file is not loaded again.
    """
    if data is None:
        path = _get_yaml_path()
        data = load_config(path)
    result = []
    for group_id, group_data in (data.get("groups") or {}).items():
        group_time = (group_data.get("default_time") or "").strip()
        if not group_time:
            raise ValueError(f"Group {group_id!r} must have 'default_time'")
        tasks = []
        for task in (group_data.get("tasks") or []):
            t = _normalize_task(
                dict(task), group_id,
                group_default_time=group_time,
            )
            if t.get("enabled") is False:
                continue
            tasks.append(t)
        if tasks:
            result.append((group_id, tasks))
    return result


def get_tasks_for_schedule(schedule_kind, day_of_week=None, day_of_month=None, interval_minutes=None, group_id=None):
    """
    Return list of (group_id, task_dict) for tasks matching the given schedule.
    Only enabled tasks. Preserves task order within each group.
    When group_id is set, only tasks from that group are returned (use for daily/weekly/monthly per-group runs).
    For interval, group_id should be None so all interval tasks with that minutes run in one independent task.
    """
    if schedule_kind not in SCHEDULE_TYPES:
        raise ValueError(f"schedule_kind must be one of {SCHEDULE_TYPES}")
    if schedule_kind == "weekly" and day_of_week is None:
        raise ValueError("day_of_week required for schedule_kind='weekly'")
    if schedule_kind == "monthly" and day_of_month is None:
        raise ValueError("day_of_month required for schedule_kind='monthly'")
    if schedule_kind == "interval" and interval_minutes is None:
        raise ValueError("interval_minutes required for schedule_kind='interval'")
    if schedule_kind == "interval" and not (1 <= int(interval_minutes) <= INTERVAL_MINUTES_MAX):
        raise ValueError(f"interval_minutes must be 1-{INTERVAL_MINUTES_MAX}")

    day_of_week_full = _normalize_day_of_week(day_of_week) if day_of_week else None
    day_of_month_int = int(day_of_month) if day_of_month is not None else None
    interval_minutes_int = int(interval_minutes) if interval_minutes is not None else None

    out = []
    for gid, tasks in get_groups_and_tasks():
        if group_id is not None and gid != group_id:
            continue
        for t in tasks:
            if t.get("schedule") != schedule_kind:
                continue
            if schedule_kind == "weekly":
                if (t.get("day_of_week") or "").lower() != (day_of_week_full or ""):
                    continue
            if schedule_kind == "monthly":
                if int(t.get("day_of_month", 0)) != day_of_month_int:
                    continue
            if schedule_kind == "interval":
                if int(t.get("minutes", 0)) != interval_minutes_int:
                    continue
            out.append((gid, t))
    return out


def _collect_distinct_schedules(data=None):
    """
    Yield (schedule_kind, day_of_week, day_of_month, time_str, interval_minutes, group_id).
    One entry per group at the group's default_time ("group batch": daily + weekly for today +
    monthly for today + on_release if new release run together in the command). Interval tasks
    get one entry per interval_minutes with group_id=None and run independently.
    If data is provided, it is passed to get_groups_and_tasks to avoid loading the file again.
    """
    seen_interval = set()
    for gid, tasks in get_groups_and_tasks(data=data):
        has_non_interval = any(t.get("schedule") != "interval" for t in tasks)
        if has_non_interval:
            time_str = (tasks[0].get("time") or DEFAULT_TIME).strip()
            yield ("daily", None, None, time_str, None, gid)
        for t in tasks:
            if t.get("schedule") == "interval":
                mins = int(t.get("minutes", 0))
                key = ("interval", None, None, None, mins, None)
                if key not in seen_interval:
                    seen_interval.add(key)
                    yield key


def get_beat_schedule():
    """
    Build CELERY_BEAT_SCHEDULE from the YAML: one entry per group (group batch at default_time)
    and one per interval_minutes. Group batch runs daily + weekly(today) + monthly(today) + on_release(if new) together.
    Returns a dict suitable for settings.CELERY_BEAT_SCHEDULE.
    If the YAML file does not exist or is invalid, returns {} (no beat schedule).
    If the YAML file does not exist or is invalid, returns {} (no beat schedule).
    """
    from datetime import timedelta

    from celery.schedules import crontab, schedule as celery_schedule

    path = _get_yaml_path()
    if not path.exists():
        logger.warning(
            "Schedule YAML not found at %s; no beat schedule loaded.",
            path,
        )
        return {}

    try:
        data = load_config(path)
    except (ValueError, yaml.YAMLError) as e:
        logger.warning("Invalid schedule YAML: %s; no beat schedule loaded.", e)
        return {}

    schedule = {}
    for row in _collect_distinct_schedules(data=data):
        schedule_kind, day_of_week, day_of_month, time_str, interval_minutes, group_id = row
        kwargs = {"schedule_kind": schedule_kind}
        if day_of_week:
            kwargs["day_of_week"] = day_of_week
        if day_of_month:
            kwargs["day_of_month"] = day_of_month
        if interval_minutes is not None:
            kwargs["interval_minutes"] = interval_minutes
        if group_id is not None:
            kwargs["group_id"] = group_id

        if schedule_kind == "interval":
            key = f"boost-collector-interval-{interval_minutes}min"
            schedule[key] = {
                "task": "boost_collector_runner.tasks.run_scheduled_collectors_task",
                "schedule": celery_schedule(run_every=timedelta(minutes=interval_minutes)),
                "kwargs": kwargs,
            }
        elif schedule_kind == "daily":
            h, m = _parse_time(time_str)
            key = f"boost-collector-group-{group_id}-{time_str.replace(':', '-')}"
            schedule[key] = {
                "task": "boost_collector_runner.tasks.run_scheduled_collectors_task",
                "schedule": crontab(hour=h, minute=m),
                "kwargs": kwargs,
            }
    return schedule
