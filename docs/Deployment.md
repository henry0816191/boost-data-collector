# Deployment

This project uses a GitHub Actions CI/CD pipeline that automatically deploys to a remote server over SSH after the CI workflow passes.

## Overview

```
Push to main/develop
      ↓
CI workflow (lint + tests)
      ↓ on success
Deploy workflow
      ↓
SSH into server → pull latest code → restart containers
```

- **`develop`** branch deploys to the **staging** environment.
- **`main`** branch deploys to the **production** environment.

---

## GitHub Environments and Secrets

The deploy workflow uses **GitHub Environments** so that each branch uses the right server. Required secrets are **environment-scoped** (`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`) and optional `SSH_PORT` (defaults to `22`) and `SSH_KEY_PASSPHRASE` — set per environment (production / staging), not as PROD_* / DEV_* repository secrets.

### 1. Create the environments

Go to **Settings → Environments** and create two environments:

- **`production`** — used when the deploy is triggered from the `main` branch.
- **`staging`** — used when the deploy is triggered from the `develop` branch.

For **production**, it is recommended to enable **Required reviewers** to add a manual approval gate before each production deploy.

### 2. Add environment secrets

In each environment (**production** and **staging**), add the following **Environment secrets** (same names in both; different values per server):

| Secret | Description |
|--------|-------------|
| `SSH_HOST` | IP address or hostname of the server |
| `SSH_USER` | SSH username (e.g. `gcp-cppdigest`) |
| `SSH_PRIVATE_KEY` | SSH private key (full content, including header/footer) |
| `SSH_PORT` | SSH port (optional, defaults to `22`) |
| `SSH_KEY_PASSPHRASE` | Passphrase for the SSH private key (optional; only if the key is passphrase-protected) |

GitHub injects the correct set based on the branch: `main` → production environment secrets, `develop` → staging environment secrets.

### 3. Optional repository secrets

These can stay as **Repository secrets** (Settings → Secrets and variables → Actions) if you use them:

| Secret | Description |
|--------|-------------|
| `DEPLOY_SCRIPT_TOKEN` | Token to authenticate downloading a custom `deploy.sh`. Required only if `DEPLOY_SCRIPT_URL` is set and needs authentication. |
| `DEPLOY_SCRIPT_URL` | Override the deploy script URL. Defaults to `deploy.sh` at the current commit SHA. |

---

## Server Prerequisites

Install these once on each server before the first deploy:

```bash
sudo apt update && sudo apt install -y git make
```

Docker and Docker Compose are also required. Refer to the [official Docker docs](https://docs.docker.com/engine/install/ubuntu/) for installation.

---

## One-Time Server Setup

### 1. Create the `.env` file (two-step process)

The deploy script does **not** manage secrets. It also requires an empty or non-existent deploy directory for the first clone: `git clone` in [deploy.sh](../.github/workflows/deploy-script/deploy.sh) fails if the target directory already exists and is not a git repo. So create `.env` **after** the first clone, not before.

**Step 1 — Trigger the first deploy**

Push to `main` or `develop` (or re-run the Deploy workflow). The script will clone the repo into `/opt/boost-data-collector` and then exit with an error because `.env` is missing.

**Step 2 — Add `.env` on the server**

SSH into the server as the same user GitHub Actions uses (e.g. `gcp-cppdigest`) and create the file inside the cloned directory. Use `.env.example` as a reference.

If you create or edit `.env` with `sudo` (e.g. `sudo nano`), the file is often owned by **root** with mode `600`. **Docker Compose reads `.env` as the user running `make build` / `make up`** (your deploy user), which causes `permission denied`. Fix ownership after saving:

```bash
sudo chown gcp-cppdigest:gcp-cppdigest /opt/boost-data-collector/.env
sudo chmod 600 /opt/boost-data-collector/.env
```

(Replace `gcp-cppdigest` with your actual `SSH_USER` if different.)

**Step 3 — Run deploy again**

Re-run the Deploy workflow (or push again). The script will see the existing repo and `.env`, and complete successfully.

### 2. Add the deploy SSH key

On your local machine, generate a dedicated deploy key:

```bash
ssh-keygen -t ed25519 -C "deploy" -f ~/.ssh/deploy_key -N ""
```

Copy the public key to the server:

```bash
ssh-copy-id -i ~/.ssh/deploy_key.pub user@your-server
```

Add the private key content (`~/.ssh/deploy_key`) as the **`SSH_PRIVATE_KEY`** secret in the **production** or **staging** environment, depending on which server you use.

---

## Remote server layout: Docker Compose + host PostgreSQL + nginx

This matches a common production/staging layout for this repo:

- **On the host:** PostgreSQL (package install), **nginx** (TLS + reverse proxy).
- **In Docker Compose:** `web` (Gunicorn), `celery_worker`, `celery_beat`, `redis`, `selenium`. The bundled **`db` service is commented out** in `docker-compose.yml`; the app uses **`DATABASE_URL`** to reach PostgreSQL on the host.

Compose already sets `extra_hosts: host.docker.internal:host-gateway` on app containers so `DATABASE_URL` can use host `host.docker.internal` (see `.env.example`). **`DATABASE_URL` is required** in `.env` for `docker compose` (there is no default to a bundled `db` service while that service stays commented out).

### Google Cloud Storage (optional seed and backups)

Example bucket name: `bdc-backups` (choose your own).

- Upload artifacts manually at first (e.g. workspace zip + DB dump).
- Prefer **`gcloud storage`** over legacy `gsutil` for copies; it is typically much faster on large objects.

Example: copy from bucket to the VM, then unpack (paths are illustrative):

```bash
gcloud storage cp "gs://bdc-backups/workspace-2026-03-24.zip" .
gcloud storage cp "gs://bdc-backups/boost-data-collector-db-2026-03-25.dump" .
unzip workspace-2026-03-24.zip -d /path/to/workspace-parent
```

Sync workspace back to the bucket (first full sync can take a long time; later syncs are incremental):

```bash
gcloud storage rsync /opt/boost-data-collector/workspace gs://bdc-backups/workspace --recursive
```

### Repository checkout and permissions

The deploy user (e.g. `gcp-cppdigest`) should own the app tree under `/opt/boost-data-collector` so `git`, `make`, and Docker Compose can run without sudo.

If the tree was created as root, normalize ownership:

```bash
sudo chown -R gcp-cppdigest:gcp-cppdigest /opt/boost-data-collector
```

Docker bind mounts for `staticfiles` (and optionally a host `workspace` directory if you use one) must be readable/writable by the **UID used inside the image** for the app process (commonly `1000`). Example:

```bash
mkdir -p /opt/boost-data-collector/staticfiles
sudo chown -R 1000:1000 /opt/boost-data-collector/staticfiles
# If using a host workspace directory mounted into the container:
sudo chown -R 1000:1000 /opt/boost-data-collector/workspace
sudo chmod -R u+rwX /opt/boost-data-collector/workspace
```

### PostgreSQL on the host (role `bdc`, database `boost_dashboard`)

Install PostgreSQL on the server (version should be compatible with your dumps and Django; this project is tested with recent PostgreSQL releases).

Create the application role and database **once** (use a strong password; the example below uses a placeholder):

```bash
sudo -u postgres psql
```

In the `psql` session:

```sql
CREATE ROLE bdc WITH LOGIN PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';
DROP DATABASE IF EXISTS boost_dashboard;
CREATE DATABASE boost_dashboard OWNER bdc;
GRANT ALL PRIVILEGES ON DATABASE boost_dashboard TO bdc;
GRANT CREATE, USAGE ON SCHEMA public TO bdc;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO bdc;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO bdc;
CREATE ROLE app_readonly NOLOGIN;
```

Run these statements as a superuser (e.g. `postgres`). The app role does not need `CREATEDB`; the database is created explicitly above. If you need a separate migration-only user with broader rights, create that role separately.

If your dump replays `GRANT … TO app_readonly`, the `app_readonly` role must exist before restore (as above).

### `pg_hba.conf`: Docker containers → host PostgreSQL

With `host.docker.internal` in `DATABASE_URL` (see `docker-compose.yml` `extra_hosts`), Postgres still sees the client as the **container’s bridge IP** (e.g. `172.20.0.4`), not `127.0.0.1`, so `host … 127.0.0.1/32` rules do not match that traffic. `pg_hba.conf` lines match **database**, **user**, and **client address**; without a matching line you may see:

```text
FATAL:  no pg_hba.conf entry for host "172.20.0.4", user "bdc", database "boost_dashboard", ...
```

Add something like (adjust user/database names and auth to match your install; `scram-sha-256` is typical):

```conf
host  boost_dashboard  bdc  172.16.0.0/12  scram-sha-256
```

**`172.16.0.0/12`** covers `172.16.0.0`–`172.31.255.255`, which includes common Docker bridge subnets. To narrow to one subnet (e.g. only `172.20.*`), use **`172.20.0.0/16`** instead.

Reload Postgres after editing:

```bash
sudo systemctl reload postgresql
```

If the client negotiates SSL but the server does not use TLS for this path, add **`?sslmode=disable`** or **`prefer`** to **`DATABASE_URL`** (see `.env.example`).

### Restoring from `pg_dump` (custom format)

Backups produced with `pg_dump -Fc` are **not** plain SQL. Restore with **`pg_restore`**, not `psql -f`. The file may still be named `*.sql` even though it is custom format—use `pg_restore`, not the extension, to decide the tool.

**Where to put the dump file**

- The **`postgres`** OS user must be able to read the file. Placing it under **`/tmp/`** with world-readable permissions (e.g. `644`) during restore is typical.

**Prefer Unix socket for superuser restore**

`sudo -u postgres pg_restore -h localhost …` often fails because **TCP** to `localhost` uses `pg_hba.conf` **password** rules, not **peer** auth. Connect via the **socket** instead (omit `-h` or use `-h /var/run/postgresql`):

```bash
sudo -u postgres pg_restore -h /var/run/postgresql -p 5432 -U postgres \
  --verbose --clean --if-exists \
  -d boost_dashboard \
  /tmp/boost-data-collector-db-2026-03-25.dump
```

**After restore — privileges for the app user:** Restore as `postgres` leaves **`public` tables owned by `postgres`**; DB owner `bdc` still has **no table rights** until you `GRANT` (empty `role_table_grants` for `bdc` is expected). Grants to other roles in the dump (e.g. `app_readonly`) do not apply to `bdc`.

1. As superuser: `\c boost_dashboard`, then run (adjust role name if not `bdc`):

```sql
GRANT USAGE ON SCHEMA public TO bdc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bdc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bdc;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO bdc;
```

2. **Check:** `pg_tables` / `information_schema` are **per database**—always `\c boost_dashboard` before querying. After grants, `SELECT COUNT(*) FROM information_schema.role_table_grants WHERE grantee = 'bdc' AND table_schema = 'public'` should be large (on the order of hundreds for a full app schema).

Repeat step 1 after any future restore that leaves table ownership on `postgres`.

### `.env` for host PostgreSQL

Set **`DATABASE_URL`** (and any `DB_*` overrides) so containers reach the host database, for example:

```bash
DATABASE_URL=postgres://bdc:REPLACE_WITH_STRONG_PASSWORD@host.docker.internal:5432/boost_dashboard
```

Also set production-safe values for:

- **`ALLOWED_HOSTS`** — your public hostname(s).
- **`CSRF_TRUSTED_ORIGINS`** — `https://your.hostname` entries for HTTPS sites.
- **`USE_X_FORWARDED_HOST=True`** and **`USE_TLS_PROXY_HEADERS=True`** when Django sits behind nginx terminating TLS (see comments in `config/settings.py`).
- **`STATIC_URL`** / **`FORCE_SCRIPT_NAME`** — only if you serve the app under a URL prefix; see the optional nginx subsection below.

### Docker stack

From `/opt/boost-data-collector` as the deploy user:

```bash
make build   # first build is slower; later builds are incremental
make up
make health  # optional smoke checks (see Makefile)
```

The deploy script runs `make down`, `make build`, `make up`, then polls `make health`.

### nginx reverse proxy

`docker-compose.yml` publishes Gunicorn on **`127.0.0.1:8000`** only. Terminate TLS on the host with nginx and proxy to that port.

#### At site root (`/`)

The following example assumes the app is served at the **domain root** (`https://collector.example.org/`) and static files at **`/static/`**.

```nginx
upstream boost_collector_app {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name collector.example.org;

    ssl_certificate     /etc/letsencrypt/live/collector.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/collector.example.org/privkey.pem;

    client_max_body_size 100M;

    location / {
        proxy_pass         http://boost_collector_app;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_redirect     off;
        proxy_read_timeout 300s;
    }

    location /static/ {
        alias /opt/boost-data-collector/staticfiles/;
    }
}
```

#### Optional: URL prefix (subpath)

If the app must live under a prefix (e.g. `https://example.org/boost-data-collector/`), set in `.env`:

- `FORCE_SCRIPT_NAME=/boost-data-collector` (no trailing slash)
- `STATIC_URL=/boost-data-collector/static/` (must end with `/`)

Example nginx (adjust the prefix string to match your `FORCE_SCRIPT_NAME`):

```nginx
upstream boost_collector_app {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name example.org;

    ssl_certificate     /etc/letsencrypt/live/example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.org/privkey.pem;

    client_max_body_size 100M;

    location /boost-data-collector/static/ {
        alias /opt/boost-data-collector/staticfiles/;
    }

    location /boost-data-collector/ {
        proxy_pass         http://boost_collector_app/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_redirect     off;
        proxy_read_timeout 300s;
    }
}
```

Reload nginx after testing config (`sudo nginx -t && sudo systemctl reload nginx`).

**Selenium (port 4444)** is bound to **`127.0.0.1:4444`** in Compose so it is not exposed on the public interface. Access from your laptop via **SSH port forwarding** if you need the hub from outside the VM:

```bash
ssh -L 4444:127.0.0.1:4444 gcp-cppdigest@YOUR_VM_IP
```

---

## Deploy Script Behavior

The deploy script (`.github/workflows/deploy-script/deploy.sh`) runs on the remote server and does the following:

1. Validates `REPO_URL` and `BRANCH` are set.
2. Checks that `git` and `make` are installed.
3. If the repo already exists — fetches and hard-resets to `origin/<branch>`.
4. If the repo does not exist — clones it fresh.
5. Checks for `.env` in the deploy directory (`$DEPLOY_DIR/.env`). If it is missing, the script exits with an error. Create `.env` after the first clone using the [two-step process](#1-create-the-env-file-two-step-process).
6. Stops existing containers (`make down`).
7. Builds and starts the stack (`make build && make up`).
8. Waits for `make health` to succeed (see `Makefile`).

### Overriding the deploy directory

By default the repo is cloned into `/opt/boost-data-collector`. To use a different path, set `DEPLOY_DIR` as an environment variable on the server or pass it via the `envs:` parameter in `deploy.yml`.

---

## Updating `.env` on the Server

When secrets or config values change, SSH into the server and edit the file directly:

```bash
nano /opt/boost-data-collector/.env
```

Ensure the deploy user still owns the file if you used `sudo` to edit:

```bash
sudo chown gcp-cppdigest:gcp-cppdigest /opt/boost-data-collector/.env
sudo chmod 600 /opt/boost-data-collector/.env
```

Then restart the containers to pick up the new values:

```bash
cd /opt/boost-data-collector && make down && make up
```

---

## Health checks (`make health`)

`make health` runs a small set of checks from the `Makefile` (Django `check --database default` inside **`web`**, `redis-cli PING`, Selenium `/status` from inside the selenium container, and `docker compose ps` for Celery services). It does **not** fully prove Celery broker connectivity or every cross-service path. Treat it as a quick smoke test after deploy.

For more detail see [Docker.md](./Docker.md) and the `health` target in the `Makefile`.
