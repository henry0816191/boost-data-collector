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
| `SSH_USER` | SSH username |
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
SSH into the server and create the file inside the cloned directory:

```bash
sudo nano /opt/boost-data-collector/.env
# paste your environment variables, save and exit
sudo chmod 600 /opt/boost-data-collector/.env
```

Use `.env.example` in the repository as a reference for the required variables. The script expects `.env` at `$DEPLOY_DIR/.env` (default: `/opt/boost-data-collector/.env`).

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

## Deploy Script Behavior

The deploy script (`.github/workflows/deploy-script/deploy.sh`) runs on the remote server and does the following:

1. Validates `REPO_URL` and `BRANCH` are set.
2. Checks that `git` and `make` are installed.
3. If the repo already exists — fetches and hard-resets to `origin/<branch>`.
4. If the repo does not exist — clones it fresh.
5. Checks for `.env` in the deploy directory (`$DEPLOY_DIR/.env`). If it is missing, the script exits with an error. Create `.env` after the first clone using the [two-step process](#1-create-the-env-file-two-step-process).
6. Stops existing containers (`make down`).
7. Builds and starts the stack (`make build && make up`).

### Overriding the deploy directory

By default the repo is cloned into `/opt/boost-data-collector`. To use a different path, set `DEPLOY_DIR` as an environment variable on the server or pass it via the `envs:` parameter in `deploy.yml`.

---

## Updating `.env` on the Server

When secrets or config values change, SSH into the server and edit the file directly:

```bash
nano /opt/boost-data-collector/.env
```

Then restart the containers to pick up the new values:

```bash
cd /opt/boost-data-collector && make down && make up
```
