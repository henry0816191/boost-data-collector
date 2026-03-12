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

## GitHub Secrets

Set these in your GitHub repo under **Settings → Secrets and variables → Actions**.

### Production (`main` branch)

| Secret | Description |
|--------|-------------|
| `PROD_SSH_HOST` | IP address or hostname of the production server |
| `PROD_SSH_USER` | SSH username |
| `PROD_SSH_PRIVATE_KEY` | SSH private key (full content, including header/footer) |
| `PROD_SSH_PORT` | SSH port (optional, defaults to `22`) |

### Staging (`develop` branch)

| Secret | Description |
|--------|-------------|
| `DEV_SSH_HOST` | IP address or hostname of the staging server |
| `DEV_SSH_USER` | SSH username |
| `DEV_SSH_PRIVATE_KEY` | SSH private key |
| `DEV_SSH_PORT` | SSH port (optional, defaults to `22`) |

### Optional

| Secret | Description |
|--------|-------------|
| `DEPLOY_SCRIPT_TOKEN` | Token to authenticate downloading a custom `deploy.sh`. Required only if `DEPLOY_SCRIPT_URL` is set and needs authentication. |
| `DEPLOY_SCRIPT_URL` | Override the deploy script URL. Defaults to `deploy.sh` at the current commit SHA. |

---

## GitHub Environments

The deploy workflow uses GitHub Environments (`production` and `staging`). Create them at **Settings → Environments**.

For `production`, it is recommended to enable **Required reviewers** to add a manual approval gate before any production deploy runs.

---

## Server Prerequisites

Install these once on each server before the first deploy:

```bash
sudo apt update && sudo apt install -y git make
```

Docker and Docker Compose are also required. Refer to the [official Docker docs](https://docs.docker.com/engine/install/ubuntu/) for installation.

---

## One-Time Server Setup

### 1. Create the `.env` file

The deploy script does **not** manage secrets. You must place `.env` manually on the server before the first deploy; if `.env` is missing, the deploy will fail with an error.

```bash
sudo mkdir -p /opt/boost-data-collector
sudo nano /opt/boost-data-collector/.env
# paste your environment variables, save and exit
sudo chmod 600 /opt/boost-data-collector/.env
```

Use `.env.example` in the repository as a reference for the required variables.

### 2. Add the deploy SSH key

On your local machine, generate a dedicated deploy key:

```bash
ssh-keygen -t ed25519 -C "deploy" -f ~/.ssh/deploy_key -N ""
```

Copy the public key to the server:

```bash
ssh-copy-id -i ~/.ssh/deploy_key.pub user@your-server
```

Add the private key content (`~/.ssh/deploy_key`) as the `PROD_SSH_PRIVATE_KEY` (or `DEV_SSH_PRIVATE_KEY`) GitHub secret.

---

## Deploy Script Behavior

The deploy script (`.github/workflows/deploy-script/deploy.sh`) runs on the remote server and does the following:

1. Validates `REPO_URL` and `BRANCH` are set.
2. Checks that `git` and `make` are installed.
3. If the repo already exists — fetches and hard-resets to `origin/<branch>`.
4. If the repo does not exist — clones it fresh.
5. Checks for `.env` in the deploy directory. If it is missing, the script exits with an error. You must create `.env` on the server before the first deploy (see [One-Time Server Setup](#1-create-the-env-file)).
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
