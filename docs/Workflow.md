# How does the main application workflow work?

## Overview

The **Boost Data Collector** is a Django project with multiple Django apps. The main workflow is driven by Django's `manage.py` and management commands (or by a Celery task that runs the same workflow). It can run on a set day (e.g. via Celery Beat). Each data-collection or processing step is a Django management command (e.g. `python manage.py run_boost_library_tracker`). The project uses one virtual environment and one database; all apps share the same Django settings and `INSTALLED_APPS`. All sub-apps run one after another - no parallel execution. This document covers: main application workflow and processes, project setup and initialization, and branching strategy for the repository.

## 1. Main application workflow and processes

### How the workflow runs

The main task runs once per day at a set time (e.g. Celery Beat, cron, or manually: `python manage.py run_all_collectors`). Each Django app exposes one or more tasks or management commands (e.g. `run_boost_library_tracker`). The main task runs them in a fixed order, one after another - only one app task runs at a time. That avoids write conflicts and keeps data dependencies between apps in order.

1. Start - Trigger the main task at the scheduled time.
2. Run app tasks in order - For each app task in the list: run it (e.g. `run_boost_library_tracker`), wait for it to finish, check exit code (0 = success, non-zero = failure), record the result; then run the next. You can optionally stop on first failure.
3. Finalize - Log how many app tasks ran and how many succeeded or failed; report the summary to maintainers (e.g. by email, Slack, or log); exit with an overall success or failure code.

## 2. Project details

- Framework - Django. One Django project with multiple Django apps; all apps share the same settings and database.
- ORM - Django ORM. All data access goes through Django models and the ORM; migrations are used for schema changes.
- Database - PostgreSQL. The project uses one PostgreSQL database (e.g. `boost_dashboard`); there are no separate databases or schema-based isolation per app.
- Task scheduling - Celery and Celery Beat run the main task once per day at **1:00 AM PST** (America/Los_Angeles) via the `workflow.tasks.run_all_collectors_task` task; Redis is the message broker. You can also run the workflow by hand via `python manage.py run_all_collectors` instead of Celery. Start the worker with `celery -A config worker -l info` and the scheduler with `celery -A config beat -l info`.
- Configuration - Django settings (e.g. `settings.py`); environment variables for database URL, credentials, and API keys (e.g. via `django-environ` or `python-decouple`).
- Structure - One Django project (e.g. `config/` or project root with `manage.py`, `settings.py`). Multiple Django apps (see table below); each app can expose management commands in `management/commands/`. All apps are in `INSTALLED_APPS` and use the shared database.

## Execution order of app tasks

The main task runs each app's task one after another. The order is set in the workflow (e.g. in `run_all_collectors` or in the Celery task). Order matters:

- Data dependencies - App tasks that produce reference or core data (e.g. Boost Library Tracker, GitHub Activity) run before app tasks that use that data (e.g. Boost Usage Tracker).
- Shared reference data - App tasks that own reference tables (e.g. language, license) run early so other app tasks can read that data.

Typical order: data-collection app tasks first, then processing or transform, then analysis or reporting. The exact list is configured in the main task.

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
