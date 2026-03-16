# Django app development guideline

This document outlines the development requirements and guidelines for Django apps in the Boost Data Collector Django project.

## Overview

- Django project: One Django project with multiple Django apps; all apps share the same virtual environment, settings, and database.
- Workflow: The project runs app tasks sequentially via management commands (e.g. `python manage.py run_boost_library_tracker`) or a single command that runs all collectors. Use **workflow** (`python manage.py run_all_collectors`) for a fixed list, or **boost_collector_runner** with `config/boost_collector_schedule.yaml` for a YAML-driven schedule. In production, Celery Beat invokes the same runner as: `python manage.py run_scheduled_collectors --schedule default --group <group_id>` for a group batch, or `python manage.py run_scheduled_collectors --schedule interval --interval-minutes <n>` for an interval batch. Manual runs (e.g. `run_all_collectors`, `run_boost_library_tracker`) differ from Beat’s per-group schedule; use the Beat-style flags above when testing the YAML-driven path.
- Configuration: Django settings (e.g. `settings.py`), environment variables for database URL and API keys (e.g. via `django-environ` or `python-decouple`).

## Django app requirements

### 1. Programming language

- Must be developed using Python.
- Must use Python 3.11+.

### 2. Entry point and dependencies

- Must expose one or more Django management commands in the app's `management/commands/` folder (e.g. `run_boost_library_tracker.py`). The main workflow invokes these commands in order—either from the **workflow** app's fixed list or from **boost_collector_runner**'s `config/boost_collector_schedule.yaml`.
- Project dependencies (including app-specific ones) are listed in the project root `requirements.txt`; all apps use the same virtual environment.

### 3. Configuration and logging

- Use Django settings for environment variables and constants (e.g. from `settings.py` or env vars loaded via `django-environ`).
- Use the project's logging configuration (`settings.LOGGING`); get a logger in your app (e.g. `logging.getLogger(__name__)`).

### 4. Database access

- Must use Django ORM for database access; all data access goes through Django models.
- Use migrations for schema changes; run `python manage.py migrate` as part of setup and deployment.
- Write access: only to your app's models (or shared models your app owns). Avoid writing to other apps' tables directly.
- Read-only access: you may read other apps' models when needed; prefer loose coupling and avoid circular imports.
- Do not define ForeignKey or ORM relationships to another app's models if it would create tight coupling or circular dependencies. To use another app's data, query it in your command or service and use the result in your logic.

### 5. Exit codes

- Management commands must exit with proper exit codes when run as scripts (e.g. from `run_all_collectors`).
- `0` for success.
- Non-zero for failure.

### 6. Restart and resume logic

- App tasks should implement restart logic so that if a command is interrupted and run again, it can resume without redoing completed work.
- Check the database or state to see what has already been done; skip already processed items to avoid duplicate work.

## What the Django project provides

The project provides:

1. Settings and configuration: `settings.py` (Django settings; database, logging, installed apps), and environment variables for database URL, credentials, and API keys (e.g. via `django-environ` or `python-decouple`).
2. Database: One PostgreSQL database shared by all apps; migrations are run from the project root.
3. Execution: `manage.py` and management commands; within a single run (e.g. `run_all_collectors` or one `run_scheduled_collectors` batch), app commands run in order sequentially. Separate Celery Beat entries may still run concurrently across workers.

## Local development setup

Use these steps to get the Django project running on your machine.

1. Clone the repository and open the project root (where `manage.py` lives).
2. Create a virtual environment (e.g. `python -m venv .venv`) and activate it.
3. Install dependencies (e.g. `pip install -r requirements.txt`).
4. Copy the sample env file (e.g. `.env.example`) to `.env` and fill in values for database URL, credentials, and any API keys (e.g. via `django-environ` or `python-decouple`).
5. Ensure the database is reachable. Run migrations: `python manage.py migrate`.
6. Run a single app command (e.g. `python manage.py run_boost_library_tracker`) or the full workflow (e.g. `python manage.py run_all_collectors`) to confirm the project works. To test the YAML-driven path as Beat does, use `python manage.py run_scheduled_collectors --schedule default --group <group_id>` for a group batch, or `python manage.py run_scheduled_collectors --schedule interval --interval-minutes <n>` for an interval batch (see `config/boost_collector_schedule.yaml`).

## Testing workflow

Run tests often so you catch problems early.

- **Before each commit:** run the test suite for the code you changed (`python -m pytest` or a subset).
- **For app commands:** ensure the command runs successfully (e.g. `python manage.py run_boost_library_tracker` exits with 0 and does the expected work).
- **Full workflow:** run `python manage.py run_all_collectors` when testing the fixed workflow, or `python manage.py run_scheduled_collectors --schedule default --group <group_id>` / `--schedule interval --interval-minutes <n>` when testing the YAML-driven path (matches how Celery Beat invokes it).
  Add tests for new behavior and keep them passing.

## Step-by-step development workflow guide

This guide walks you from setup to merged code.

1. Set up locally - Follow "Local development setup" above.
2. Create a feature branch - Branch from `develop` (e.g. `git checkout develop && git pull && git checkout -b feature/your-feature-name`).
3. Develop and test - Make your changes in the Django app. Run the testing workflow (e.g. run tests and the app command) after each logical change.
4. Commit and push - Commit with clear messages and push the feature branch to the remote.
5. Open a pull request - Open a PR targeting the `develop` branch. Describe what changed and how to test it.
6. Address review - Respond to reviewer comments and update the PR as needed.
7. Merge - After approval and passing checks, merge into `develop`. Follow "Merge Process" below for exact steps.
8. Adding a new Django app - Add the app to `INSTALLED_APPS`, create models and migrations, add a management command in `management/commands/`, and either add the command to the list run by `run_all_collectors` (workflow app) or add it to `config/boost_collector_schedule.yaml` under the right group and schedule (boost_collector_runner). Update docs as needed.

## Development workflow

### Django app development

1. Create feature branch from `develop` branch.
2. Develop and test your app locally (run tests and the app command).
3. Create pull request targeting `develop` branch in the project repository.
4. Wait for review and address feedback.

### Adding a new Django app to the project

1. Create the app (e.g. `python manage.py startapp my_app` or add the app folder to the project).
2. Add the app to `INSTALLED_APPS` in settings.
3. Add a management command (e.g. in `my_app/management/commands/run_my_app.py`) that runs the app logic and returns the correct exit code.
4. Add the command to the list run by `run_all_collectors` (workflow app) or add it to `config/boost_collector_schedule.yaml` under the right group with the right schedule (see [Workflow.md](Workflow.md#2-boost-collector-runner-and-yaml-schedule)).
5. Create and run migrations; update documentation.

## Review process

### Django app pull request review

Reviewers should check:

1. Security and malicious code: Check for code that could expose internal information; review outbound requests; verify no sensitive data (credentials, URLs, tokens) is sent out; ensure no hardcoded credentials or secrets.
2. Code quality: Developed using Python; follows Python and Django best practices; proper error handling.
3. Database access: Uses Django ORM; only writes to own app's models; read-only access to other apps when needed; no tight coupling or circular imports; migrations included and applied.
4. Integration: Uses Django settings and logging; has a management command in `management/commands/`; command is in the run order if it is a collector; implements restart logic where needed.
5. Testing: Tests included and passing; app command runs successfully; no breaking changes.
6. Documentation: README or docstrings updated if needed; code comments where appropriate.

## Merge process

### Project repository

1. Pull request approved by reviewers.
2. All checks passing (tests, linting, etc.).
3. Merge to `develop` branch:
   ```bash
   git checkout develop
   git merge feature/your-feature-name
   git push origin develop
   ```
4. After testing, merge to `main` when ready for production.

## Branching strategy

- master: Main/production branch (stable code).
- develop: Development branch (active development).
- Feature branches: Created from `develop` for features. Developers must branch from `develop`; do not branch from `main`.

Pull requests target the `develop` branch.

## Key points:

- Command lives in `my_app/management/commands/run_my_app.py` (name must match the command: `run_my_app`).
- Uses Django logging and Django ORM; no separate session or config module.
- Returns 0 for success, non-zero for failure so `run_all_collectors` or `run_scheduled_collectors` can detect failures.
- Implement restart logic inside the task (check what is already processed and skip it).

## Related documentation

- [Workflow.md](Workflow.md) - Main application workflow and execution order.
- [Schema.md](Schema.md) - Database schema and table relationships.
- [README.md](../README.md) - Project overview and quick start.
