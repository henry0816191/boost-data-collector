# Docker setup – Boost Data Collector

This guide explains how to run the project with Docker. It is written for people who are new to Docker.

---

## What you need to know

- **Docker** runs your app and its dependencies (PostgreSQL, Redis, Selenium) in isolated containers.
- **Docker Compose** starts multiple containers together and wires them (e.g. app → database).
- You do **not** need to install Python or PostgreSQL on your machine to run the app with Docker.

---

## 1. Install Docker

1. **Install Docker Desktop** (includes Docker and Docker Compose):
   - **Mac/Windows:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - **Linux:** Install Docker Engine and Docker Compose plugin (see [Docker docs](https://docs.docker.com/engine/install/) for your distro).

2. **Check that it works.** Open a terminal and run:

   ```bash
   docker --version
   docker compose version
   ```

   You should see version numbers. If you get “command not found,” Docker is not on your PATH or not installed.

---

## 2. Prepare the project

1. **Go to the project folder:**

   ```bash
   cd /path/to/boost-data-collector
   ```

2. **Create a `.env` file** (Docker Compose and Django read this):

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` and set at least:
   - **Database:** Docker Compose will start PostgreSQL. You can use these defaults in `.env` (they match `docker-compose.yml`):

     ```bash
     POSTGRES_USER=boost
     POSTGRES_PASSWORD=boost
     POSTGRES_DB=boost_dashboard
     ```

     And set Django’s database URL so it points at the `db` container:

     ```bash
     DATABASE_URL=postgres://boost:boost@db:5432/boost_dashboard
     ```

   - **Django:** Set a strong `SECRET_KEY` (and optionally `DEBUG=True` for local use).

   - **Optional:** Add any API keys you need (e.g. `GITHUB_TOKEN`, `SLACK_BOT_TOKEN`) as in `.env.example`.

   Compose will pass `DATABASE_URL`, `CELERY_BROKER_URL`, etc. to the app; the `db` and `redis` hostnames are the service names in `docker-compose.yml`.

---

## 3. Build and start everything

From the project root:

```bash
docker compose build
```

This builds the app image (installs Python and dependencies). Do this once, or after changing `requirements.txt` or the `Dockerfile`.

Then start all services:

```bash
docker compose up -d
```

**On macOS (especially with the project on an external volume):** To avoid Docker build errors caused by macOS `._*` files, use `make up` instead (see below). It automatically cleans those files before starting Compose.

- **`up`** = start the containers.
- **`-d`** = “detached” (run in the background so you get your terminal back).

Containers that will run:

| Service           | Role              | Port / note                                                   |
| ----------------- | ----------------- | ------------------------------------------------------------- |
| **db**            | PostgreSQL        | Internal only                                                 |
| **redis**         | Redis (Celery)    | Internal only                                                 |
| **selenium**      | Chrome (Selenium) | **http://localhost:4444** (for cppa_slack_transcript_tracker) |
| **web**           | Django (gunicorn) | **http://localhost:8000**                                     |
| **celery_worker** | Celery worker     | Runs tasks                                                    |
| **celery_beat**   | Celery beat       | Schedules daily job (schedule persisted in volume)            |

---

## 4. First-time setup: run migrations

The database is empty at first. Run Django migrations **inside** the `web` container:

```bash
docker compose run --rm web python manage.py migrate
```

- **`run`** = run a one-off command in a service.
- **`--rm`** = remove the temporary container when the command finishes.
- **`web`** = use the app image and env (DB connection, etc.).

After this, the app is ready to use.

---

## 5. Open the app

In your browser go to:

**http://localhost:8000**

You should see the Django app (or admin if you configured it).

---

## 6. Make commands (recommended)

The project includes a `Makefile`. From the project root, run `make help` to see all available commands:

```
make build          # Build (or rebuild) all images
make up             # Clean macOS files, then start all services (detached)
make down           # Stop and remove containers (volumes kept)
make stop           # Pause all containers (fast restart with: make start)
make start          # Resume paused containers
make restart        # Stop then start all containers
make reset          # !! Remove containers AND volumes (wipes DB + data)

make ps             # Show running containers
make logs           # Follow logs for all services
make logs-web       # Follow web logs only
make logs-worker    # Follow Celery worker logs
make logs-beat      # Follow Celery beat logs

make migrate        # Apply database migrations
make makemigrations # Create new migration files
make superuser      # Create a Django superuser
make shell          # Open Django shell inside the web container
make bash           # Open a bash shell inside the web container
make collectstatic  # Collect static files

make test           # Run full pytest suite
make test-fast      # Run tests, stop on first failure

make clean-mac      # Remove macOS ._* resource-fork files
make clean-pyc      # Remove compiled Python (.pyc / __pycache__)
make clean          # Run both clean-mac and clean-pyc
```

The `make up` / `make build` targets always run `clean-mac` first, so you never hit the macOS xattr build error on external volumes.

---

## 7. Useful commands (reference)

- **See running containers:**

  ```bash
  docker compose ps
  ```

- **View logs** (all services):

  ```bash
  docker compose logs -f
  ```

  Logs for one service only:

  ```bash
  docker compose logs -f web
  docker compose logs -f celery_worker
  ```

- **Stop everything:**

  ```bash
  docker compose down
  ```

  Data in the `postgres_data`, `workspace_data`, `logs_data`, and `celerybeat_data` volumes is kept.

- **Stop and remove volumes** (deletes database and workspace data):

  ```bash
  docker compose down -v
  ```

- **Run a one-off command** (e.g. Django management command):

  ```bash
  docker compose run --rm web python manage.py run_all_collectors
  docker compose run --rm web python manage.py createsuperuser
  ```

- **Rebuild after code or dependency changes:**
  ```bash
  docker compose build
  docker compose up -d
  ```

---

## 8. Troubleshooting

- **“Cannot connect to database” / “connection refused”**
  Wait a few seconds after `docker compose up -d` and run migrations again. The `web` service waits for `db` to be healthy before starting.

- **Port 8000 already in use**
  Change the host port in `docker-compose.yml` under `web` → `ports`, e.g. `"9000:8000"`, then use http://localhost:9000.

- **Changes in code not visible**
  Rebuild: `docker compose build web` then `docker compose up -d`.

- **Need to see what’s inside a container**
  ```bash
  docker compose exec web bash
  ```
  Then you can run `python manage.py shell`, `ls`, etc. Exit with `exit`.

---

## Summary

1. Install Docker (Desktop or Engine + Compose).
2. Copy `.env.example` to `.env` and set `DATABASE_URL` (and optional secrets).
3. Run `docker compose build` then `docker compose up -d`.
4. Run `docker compose run --rm web python manage.py migrate`.
5. Open http://localhost:8000.

For more on Docker, see [Docker’s getting-started guide](https://docs.docker.com/get-started/).
