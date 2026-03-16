# How does the main application workflow work?

## Overview

The **Boost Data Collector** is a Django project with multiple Django apps. The main workflow is driven by Django's `manage.py` and management commands (or by Celery tasks that run the same commands). Each data-collection or processing step is a Django management command (e.g. `python manage.py run_boost_library_tracker`). The project uses one virtual environment and one database; all apps share the same Django settings and `INSTALLED_APPS`. Within a single command run—e.g. `python manage.py run_all_collectors` or `python manage.py run_scheduled_collectors`—collectors run one after another with no parallel execution; different Celery Beat entries (such as `workflow.tasks.run_all_collectors_task` or the YAML-driven groups in `config/boost_collector_schedule.yaml`) can run in parallel across workers.

You can run collectors in two ways:

- **workflow app** – Fixed list: `python manage.py run_all_collectors`. Celery Beat can run `workflow.tasks.run_all_collectors_task` on a schedule.
- **boost_collector_runner app** – YAML-driven schedule: `config/boost_collector_schedule.yaml` defines groups, schedule types (daily, weekly, monthly, interval, on_release), and optional args. Use `python manage.py run_scheduled_collectors --schedule daily` (or weekly/monthly/interval/on_release). Celery Beat is built from the YAML so adding or reordering collectors requires no code changes—only editing the YAML.

This document covers: main workflow process, Boost Collector Runner and YAML schedule, project details, execution order, error handling, and branching.

## 1. Main workflow process

### How the workflow runs

The main task runs at a set time (e.g. Celery Beat) or on demand. Each Django app exposes one or more management commands (e.g. `run_boost_library_tracker`). The runner runs them in order, one at a time, to avoid write conflicts and keep data dependencies in order.

1. **Start** – Trigger the run (Beat, cron, or `python manage.py run_all_collectors` / `run_scheduled_collectors`).
2. **Run commands in order** – For each command: run it, wait for completion, check exit code (0 = success, non-zero = failure), then run the next. Optionally stop on first failure.
3. **Finalize** – Log how many succeeded or failed; exit with an overall success or failure code.

## 2. Boost Collector Runner and YAML schedule

The **boost_collector_runner** app runs collectors from a single config file so you can add, reorder, or reschedule tasks without changing Python code.

### Config file

- **Path:** `config/boost_collector_schedule.yaml`
- **Setting:** `BOOST_COLLECTOR_SCHEDULE_YAML` in `config/settings.py` (defaults to that path).

### Schedule types

| Type | Meaning |
|------|--------|
| **daily** | Run every day at the group's default_time. |
| **weekly** | Run once per week. Use **on** with a weekday: `monday`, `mon`, `tuesday`, `tue`, etc. |
| **monthly** | Run once per month on a given date. Use **on** with day of month (1–31). |
| **interval** | Run every N **minutes**. Use **minutes** (1–180). **Use interval only for minutes; at most 3 hours.** Suitable for short periodic runs (e.g. every 15 min). |
| **on_release** | Run when a new version release is detected. There is no dedicated Beat entry for `on_release`; grouped `on_release` tasks are evaluated during group batch runs, and standalone checks can also be triggered manually or from release-detection code (e.g. `run_scheduled_collectors_task.delay(schedule_kind="on_release")`). |

### Structure

- **groups:** Each group has **default_time** (required; 24h `"HH:MM"`, UTC) and a **tasks** list.
- **Each task:**
  - **command** (required) – Management command name (e.g. `run_boost_library_tracker`).
  - **schedule** (required) – `daily` | `weekly` | `monthly` | `interval` | `on_release`.
  - **on** – For **weekly**: weekday name (`monday` or `mon`, etc.). For **monthly**: day of month (1–31). Omit for daily, interval, and on_release.
  - **minutes** – For **interval** only: run every N minutes (1–180; at most 3 hours). Use interval only for minute-based runs.
  - **enabled** (optional) – `true` (default) or `false` to skip without removing the entry.
  - **args** (optional) – List of strings passed to the command (e.g. `["--format", "json"]`).

  Tasks do not have their own **time**; the group's **default_time** is when that group's non-interval tasks run. Within a group, tasks run sequentially. Each group has its own Celery Beat entry so groups can run in parallel on different workers. Interval tasks are configured under groups but excluded from the group batch; they get separate Beat entries and run independently. Tasks with `schedule: on_release` do not get a dedicated Beat entry but are included in the group batch when the group runs (and run if a new release is detected).

### Example (excerpt)

```yaml
groups:
  github:
    default_time: "04:10"
    tasks:
      - command: run_boost_library_tracker
        schedule: daily
      - command: run_boost_usage_tracker
        schedule: weekly
        on: monday
  reporting:
    default_time: "06:00"
    tasks:
      - command: run_monthly_report
        schedule: monthly
        on: 3
      - command: run_on_release_sync
        schedule: on_release
      - command: run_export
        schedule: daily
        args: ["--format", "json"]
```

### Running from the command line

- **Daily:** `python manage.py run_scheduled_collectors --schedule daily` (all groups) or `--schedule daily --group github` (one group).
- **Weekly (e.g. Monday):** `python manage.py run_scheduled_collectors --schedule weekly --day-of-week monday` or add `--group <name>` for one group.
- **Monthly (e.g. 3rd):** `python manage.py run_scheduled_collectors --schedule monthly --day-of-month 3` or add `--group <name>` for one group.
- **Interval (e.g. every 15 min):** `python manage.py run_scheduled_collectors --schedule interval --interval-minutes 15` (runs all interval tasks with that minutes; no group).
- **On release:** `python manage.py run_scheduled_collectors --schedule on_release`

Add `--stop-on-failure` to stop after the first failing command.

### Celery Beat

`CELERY_BEAT_SCHEDULE` is built from the YAML: one Beat entry **per group** for daily/weekly/monthly (so groups run in parallel), and one entry per interval-minutes for interval tasks (run independently, not tied to a group). Tasks with `schedule: on_release` do not get dedicated Beat entries; grouped `on_release` tasks are checked during group runs, and standalone `on_release` runs can be triggered from release-detection logic.

## 3. Project details

- Framework - Django. One Django project with multiple Django apps; all apps share the same settings and database.
- ORM - Django ORM. All data access goes through Django models and the ORM; migrations are used for schema changes.
- Database - PostgreSQL. The project uses one PostgreSQL database (e.g. `boost_dashboard`); there are no separate databases or schema-based isolation per app.
- Task scheduling – Celery and Celery Beat run tasks on a schedule defined by configuration (for YAML-driven runs, by each group’s `default_time`). The **boost_collector_runner** app builds the Beat schedule from `config/boost_collector_schedule.yaml` when the YAML loads successfully; if the YAML is missing or invalid, `CELERY_BEAT_SCHEDULE` is set to `{}` (no autogenerated schedule)—there is no fallback to the workflow app’s daily task. Redis is the message broker. Run by hand: `python manage.py run_all_collectors` or `python manage.py run_scheduled_collectors --schedule daily`. Start the worker with `celery -A config worker -l info` and the scheduler with `celery -A config beat -l info`.
- Configuration - Django settings (e.g. `settings.py`); environment variables for database URL, credentials, and API keys (e.g. via `django-environ` or `python-decouple`).
- Structure - One Django project (e.g. `config/` or project root with `manage.py`, `settings.py`). Multiple Django apps (see table below); each app can expose management commands in `management/commands/`. All apps are in `INSTALLED_APPS` and use the shared database.

## Execution order of app tasks

The runner executes each app's command one after another. Order is defined by the **workflow** app's fixed list (`run_all_collectors`) or by the **boost_collector_runner** YAML (order of groups and order of tasks within each group). Order matters:

- Data dependencies - App tasks that produce reference or core data (e.g. Boost Library Tracker, GitHub Activity) run before app tasks that use that data (e.g. Boost Usage Tracker).
- Shared reference data - App tasks that own reference tables (e.g. language, license) run early so other app tasks can read that data.

Typical order: data-collection first, then processing or transform, then analysis or reporting. When using the YAML, set the order by arranging groups and tasks in `config/boost_collector_schedule.yaml`.

## Error handling

- If startup checks fail (e.g. missing settings, database unreachable), the main task can exit right away with a non-zero code.
- When an app's task returns non-zero or raises an uncaught exception, the main task records the failure. The project can choose "stop on first failure" or "continue and run remaining app tasks".
- The overall exit code is 0 only when all app tasks succeeded; otherwise it is non-zero so CI or schedulers can detect failure.

## Logging

- The Django project sets up logging in `settings.LOGGING`. App tasks (management commands or Celery tasks) use this configuration.
- Log the start and end of each app task, success or failure, and exit codes. You can also write a final summary (how many ran, how many succeeded or failed) to the log or stdout.

## Branching

The repository uses two long-lived branches:

- **main** – Default branch; production-ready code. CI and deployments typically track `main`.
- **develop** – Integration branch for active development. Feature branches are created from `develop`, and pull requests target `develop`. Code is merged from `develop` into `main` for releases.

See the [README](../README.md#branching-strategy) for the full branching strategy.

## Related documentation

- [Schema.md](Schema.md) - Database schema and table relationships.
- [README.md](../README.md) - Project overview and quick start.
- [Development_guideline.md](Development_guideline.md) - Development setup, app structure, and code examples (if present).
