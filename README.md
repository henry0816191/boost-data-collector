# Boost Data Collector - Django project

## Overview

Boost Data Collector is a Django project that collects and manages data from various Boost-related sources. The project has multiple Django apps in one repository. All apps share one virtual environment, one database (PostgreSQL), and the same Django settings. Each app exposes one or more management commands (e.g. `run_boost_library_tracker`). The main workflow runs these commands in a fixed order (e.g. via `python manage.py run_all_collectors` or a Celery task). See [docs/Workflow.md](docs/Workflow.md) for workflow details.

## Quick start

### Prerequisites

- Python 3.11+
- Django (version in `requirements.txt`)
- PostgreSQL database access
- Environment variables for database URL and API keys (e.g. via `.env`)

### Initial setup

1. Clone the repository:

```bash
git clone <boost-data-collector-repo-url>
cd boost-data-collector
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Configure environment variables (e.g. copy `.env.example` to `.env` and set database URL and API credentials).

5. Create and run migrations (required before any command that uses the database):

```bash
python manage.py makemigrations
python manage.py migrate
```

Each project app has a `migrations/` package; if you previously saw "No changes detected" but `migrate` only listed `admin, auth, contenttypes, sessions`, ensure those packages exist and run the commands again. After a successful `migrate` you should see migrations for `cppa_user_tracker`, `github_activity_tracker`, `boost_library_tracker`, `workflow` (and optionally `github_ops`).

If you see `relation "cppa_user_tracker_githubaccount" does not exist` (or similar), the database tables are missing — run the two commands above.

6. Run a single app command or the full workflow to confirm the project works:

```bash
python manage.py run_all_collectors
```

For local development you can also start the dev server: `python manage.py runserver`.

## Running tests

The project uses **pytest** with **pytest-django**. Tests run against `config.test_settings` (SQLite in-memory by default; set `DATABASE_URL` to use PostgreSQL).

1. Install test dependencies (once):

```bash
pip install -r requirements-dev.txt
```

2. Run the full test suite:

```bash
python -m pytest
```

3. Optional: run with coverage and a short traceback:

```bash
python -m pytest --tb=short --cov=. --cov-report=term-missing
```

4. Run a subset of tests (e.g. one app or one file):

```bash
python -m pytest cppa_user_tracker/tests/ -v
python -m pytest github_activity_tracker/tests/test_sync_utils.py -v
```

See [docs/Development_guideline.md](docs/Development_guideline.md#testing-workflow) for when to run tests during development.

## Project structure

```
boost-data-collector/
├── manage.py
├── requirements.txt
├── .env.example
├── README.md
├── config/ or <project_name>/   # Django project settings (settings.py)
├── docs/                         # Documentation (per-topic)
│   ├── README.md                 # Topic index
│   ├── operations/               # Shared I/O (GitHub, Discord, etc.)
│   │   ├── README.md
│   │   └── github.md
│   ├── service_api/              # Per-app service API
│   ├── Workflow.md
│   ├── Schema.md
│   └── ...
├── workspace/                    # Raw/processed files (see docs/Workspace.md)
│   ├── github_activity_tracker/
│   ├── boost_library_tracker/
│   ├── ...
│   └── shared/
|   (Django Apps)
├── cppa_user_tracker/
├── github_activity_tracker/
├── workflow/
└──     ...
```

Each Django app can expose management commands in `management/commands/`. All apps are in `INSTALLED_APPS` and use the shared database.

## How it works

- Django project: One Django project with multiple Django apps; all apps share the same settings and database.
- Workflow: The main task runs app commands in a fixed order (e.g. `run_all_collectors` or a Celery task). Scheduling is done with Celery Beat or by running commands by hand.
- Database: One PostgreSQL database (e.g. `boost_dashboard`); Django ORM and migrations for all apps.
- Configuration: Django settings (`settings.py`) and environment variables (e.g. via `django-environ` or `python-decouple`).

## GitHub tokens

The project supports multiple GitHub tokens for different operations (see `.env.example`):

- **GITHUB_TOKEN** – Fallback when a specific token is not set.
- **GITHUB_TOKENS_SCRAPING** – Comma-separated list for API read/scraping; tokens are used in round-robin to spread rate limits.
- **GITHUB_TOKEN_WRITE** – Used for create PR, create issue, comment on issue, and git push (falls back to GITHUB_TOKEN).

**Operations (shared I/O):** External integrations (GitHub, Discord, etc.) live in dedicated apps (e.g. **github_ops**) and are used by other apps. See **[docs/operations/](docs/operations/)** for the group and **[docs/operations/github.md](docs/operations/github.md)** for GitHub usage and token mapping.

## Workspace (raw/processed files)

One folder, subfolders per app. For **github_activity_tracker**, sync uses `workspace/github_activity_tracker/<owner>/<repo>/commits|issues|prs/*.json`; files are processed into the DB then removed. Default root: `workspace/` (configurable via `WORKSPACE_DIR`). See [docs/Workspace.md](docs/Workspace.md).

## Documentation

Docs are organized **by topic** (one doc per concern: workflow, workspace, service API, etc.). See **[docs/README.md](docs/README.md)** for the full index.

- [docs/README.md](docs/README.md) – Per-topic index and how to find app-specific info.
- [Running tests](#running-tests) – How to run the test suite (pytest, coverage).
- [operations/](docs/operations/README.md) – **Operations group:** shared I/O (GitHub, Discord, etc.); index and per-operation docs.
- [Workflow.md](docs/Workflow.md) – Main application workflow, execution order, and project details.
- [operations/github.md](docs/operations/github.md) – GitHub layer (clone, push, fetch file, create PR/issue/comment) and token use.
- [Workspace.md](docs/Workspace.md) – Workspace layout and usage for file processing.
- [Schema.md](docs/Schema.md) – Database schema and table relationships.
- [Development_guideline.md](docs/Development_guideline.md) – Development setup, app requirements, and step-by-step workflow.
- [Contributing.md](docs/Contributing.md) – Service layer (single place for writes) and contributor guidelines.
- [Service_API.md](docs/Service_API.md) – API reference and index for all service layer functions.
- [service_api/](docs/service_api/) – Per-app service API docs (name, description, parameters, return types, validation).

## Branching strategy

- **main** – Default/production branch (stable, release-ready code).
- **develop** – Development branch (active integration and feature work).
- Feature branches: Create from `develop`. Do not branch from `main` for day-to-day work.
- Pull requests: Open PRs against `develop`; merge to `main` for releases.
