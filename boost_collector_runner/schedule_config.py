"""
Load and validate boost collector schedule YAML; expose groups/tasks and Celery Beat schedule.
Config file: config/boost_collector_schedule.yaml (see docs/Workflow.md).

Times in the YAML (default_time) are in UTC. They are not converted; Beat runs at that
UTC time (requires CELERY_ENABLE_UTC = True). For the default batch, weekly/monthly
eligibility uses the UTC date at run time so it matches the UTC default_time.

Execution model: Tasks within a group run sequentially. Each group has one Beat entry (at the
group's default_time); when it runs, all non-interval tasks in that group run together: daily,
weekly (if today matches), monthly (if today matches), and on_release (if a new Boost release
exists). So no two distinct tasks in the same group run in separate batches (except interval
tasks, which run in separate Beat entries and are independent). Interval tasks are not part of
a group run; they get separate Beat entries and run independently.
"""

import logging
import calendar
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Group batch (daily + weekly for today + monthly for today + on_release) uses this to separate from "daily" only.
DEFAULT_GROUP_BATCH_SCHEDULE_KIND = "default"

# Allowed in YAML task "schedule" (user-facing). "default" is internal only, not valid in YAML.
TASK_SCHEDULE_TYPES = (
    "daily",
    "weekly",
    "monthly",
    "on_release",
    "interval",
)
SCHEDULE_TYPES = (
    *TASK_SCHEDULE_TYPES,
    DEFAULT_GROUP_BATCH_SCHEDULE_KIND,
)
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
    """Return Path to the boost collector schedule YAML (from settings or default config path)."""
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
    try:
        h, m = int(parts[0], 10), int(parts[1], 10)
    except ValueError:
        raise ValueError(f"Invalid time {s!r}; use HH:MM") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid time {s!r}")
    return h, m


def _normalize_task(task, group_id):
    """Build a normalized task dict; default enabled=True; time is always the group's default_time (tasks do not have their own time)."""
    t = dict(task)
    t.setdefault("enabled", True)
    if t.get("enabled") is False:
        return t
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

    # args already validated in _validate_task (list of strings)
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
    if schedule not in TASK_SCHEDULE_TYPES:
        raise ValueError(
            f"Task {command!r} in group {group_id!r}: "
            f"'schedule' must be one of {TASK_SCHEDULE_TYPES}"
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
        if on_val is None:
            raise ValueError(
                f"Task {command!r} in group {group_id!r}: "
                f"'schedule: monthly' requires 'on' (1-31, day of month)"
            )
        try:
            day_int = int(on_val)
        except (TypeError, ValueError):
            raise ValueError(
                f"Task {command!r} in group {group_id!r}: "
                f"'schedule: monthly' requires 'on' (1-31, day of month)"
            ) from None
        if not (1 <= day_int <= 31):
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
    if "args" in task and not isinstance(task["args"], list):
        raise ValueError(
            f"Task {command!r} in group {group_id!r}: 'args' must be a list of strings"
        )
    if "args" in task:
        for i, a in enumerate(task["args"]):
            if not isinstance(a, str):
                raise ValueError(
                    f"Task {command!r} in group {group_id!r}: 'args[{i}]' must be a string"
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
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("Group id must be a non-empty string")
        if not isinstance(group_data, dict):
            raise ValueError(f"Group {group_id!r} must be a dict")
        raw_group_time = group_data.get("default_time")
        if not isinstance(raw_group_time, str) or not raw_group_time.strip():
            raise ValueError(
                f"Group {group_id!r} must have 'default_time' (e.g. \"04:10\")"
            )
        group_time = raw_group_time.strip()
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
        for task in group_data.get("tasks") or []:
            t = _normalize_task(
                dict(task),
                group_id,
            )
            if t.get("enabled") is False:
                continue
            tasks.append(t)
        if tasks:
            result.append((group_id, group_time, tasks))
    return result


def get_tasks_for_schedule(
    schedule_kind,
    day_of_week=None,
    day_of_month=None,
    interval_minutes=None,
    group_id=None,
    month=None,
    year=None,
    data=None,
):
    """
    Return list of (group_id, task_dict) for tasks matching the given schedule.
    Only enabled tasks. Preserves task order within each group.
    When group_id is set, only tasks from that group are returned (use for daily/weekly/monthly per-group runs).
    For interval: when group_id is provided, only interval tasks in that group with that minutes are returned
    (one independent task per group per interval); when group_id is None, all interval tasks with that
    minutes run in one task.
    For monthly: when month and year are provided, a task with day_of_month > last day of that month
    (e.g. 30 or 31) runs on the last day of the month (e.g. Feb 28/29).

    data: optional preloaded config dict (e.g. from load_config(path)). When provided, the YAML file
    is not read again; use this to avoid repeated disk I/O when calling get_tasks_for_schedule
    multiple times. When data is passed it must already be validated (e.g. by load_config()).
    """
    if schedule_kind not in SCHEDULE_TYPES:
        raise ValueError(f"schedule_kind must be one of {SCHEDULE_TYPES}")
    if schedule_kind == "weekly" and day_of_week is None:
        raise ValueError("day_of_week required for schedule_kind='weekly'")
    if schedule_kind == "weekly" and _normalize_day_of_week(day_of_week) is None:
        raise ValueError("day_of_week must be monday..sunday or mon..sun")
    if schedule_kind == "monthly" and day_of_month is None:
        raise ValueError("day_of_month required for schedule_kind='monthly'")
    if schedule_kind == "monthly":
        try:
            day_of_month = int(day_of_month)
        except (TypeError, ValueError):
            raise ValueError("day_of_month must be an integer") from None
        if not (1 <= day_of_month <= 31):
            raise ValueError("day_of_month must be 1-31")
    if schedule_kind == "interval" and interval_minutes is None:
        raise ValueError("interval_minutes required for schedule_kind='interval'")
    if schedule_kind == "interval":
        try:
            interval_minutes_int = int(interval_minutes)
        except (TypeError, ValueError):
            raise ValueError("interval_minutes must be an integer") from None
        if not (1 <= interval_minutes_int <= INTERVAL_MINUTES_MAX):
            raise ValueError(f"interval_minutes must be 1-{INTERVAL_MINUTES_MAX}")

    day_of_week_full = _normalize_day_of_week(day_of_week) if day_of_week else None
    day_of_month_int = int(day_of_month) if day_of_month is not None else None
    interval_minutes_int = (
        int(interval_minutes) if interval_minutes is not None else None
    )

    out = []
    for gid, _, tasks in get_groups_and_tasks(data=data):
        if group_id is not None and gid != group_id:
            continue
        for t in tasks:
            if (
                schedule_kind != DEFAULT_GROUP_BATCH_SCHEDULE_KIND
                and t.get("schedule") != schedule_kind
            ):
                continue
            if (
                schedule_kind == DEFAULT_GROUP_BATCH_SCHEDULE_KIND
                and t.get("schedule") == "interval"
            ):
                continue
            if t.get("schedule") == "weekly":
                if (t.get("day_of_week") or "").lower() != (day_of_week_full or ""):
                    continue
            if t.get("schedule") == "monthly":
                task_day = int(t.get("day_of_month", 0))
                if month is not None and year is not None:
                    _, last_day = calendar.monthrange(year, month)
                    effective_day = min(task_day, last_day)
                else:
                    effective_day = task_day
                if effective_day != day_of_month_int:
                    continue
            if schedule_kind == "interval":
                if int(t.get("minutes", 0)) != interval_minutes_int:
                    continue
            out.append((gid, t))
    return out


def _collect_distinct_schedules(data=None):
    """
    Yield (schedule_kind, time_str, interval_minutes, group_id).
    One entry per group at the group's default_time ("group batch": daily + weekly for today +
    monthly for today + on_release if new release run together in the command). Interval tasks
    get one entry per interval_minutes with group_id=None and run independently.
    If data is provided, it is passed to get_groups_and_tasks to avoid loading the file again.
    """
    seen_interval = set()
    for gid, group_time, tasks in get_groups_and_tasks(data=data):
        has_non_interval = any(t.get("schedule") != "interval" for t in tasks)
        if has_non_interval:
            yield (DEFAULT_GROUP_BATCH_SCHEDULE_KIND, group_time, None, gid)
        for t in tasks:
            if t.get("schedule") == "interval":
                mins = int(t.get("minutes", 0))
                key = ("interval", None, mins, None)
                if key not in seen_interval:
                    seen_interval.add(key)
                    yield key


def get_beat_schedule():
    """
    Build CELERY_BEAT_SCHEDULE from the YAML: one entry per group (group batch at default_time)
    and one per interval_minutes. Group batch runs daily + weekly(today) + monthly(today) + on_release(if new) together.
    Returns a dict suitable for settings.CELERY_BEAT_SCHEDULE.
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
    except (ValueError, yaml.YAMLError, OSError) as e:
        logger.warning("Invalid schedule YAML: %s; no beat schedule loaded.", e)
        return {}

    schedule = {}
    for row in _collect_distinct_schedules(data=data):
        (
            schedule_kind,
            time_str,
            interval_minutes,
            group_id,
        ) = row
        kwargs = {"schedule_kind": schedule_kind}
        if interval_minutes is not None:
            kwargs["interval_minutes"] = interval_minutes
        if group_id is not None:
            kwargs["group_id"] = group_id

        if schedule_kind == "interval":
            # Interval entries are global (no group_id); one Beat entry per interval_minutes.
            key = f"boost-collector-interval-{interval_minutes}min"
            schedule[key] = {
                "task": "boost_collector_runner.tasks.run_scheduled_collectors_task",
                "schedule": celery_schedule(
                    run_every=timedelta(minutes=interval_minutes)
                ),
                "kwargs": kwargs,
            }
        elif schedule_kind == DEFAULT_GROUP_BATCH_SCHEDULE_KIND:
            h, m = _parse_time(time_str)
            key = f"boost-collector-group-{group_id}-{time_str.replace(':', '-')}"
            schedule[key] = {
                "task": "boost_collector_runner.tasks.run_scheduled_collectors_task",
                "schedule": crontab(hour=h, minute=m),
                "kwargs": kwargs,
            }
    return schedule
