#!/usr/bin/env bash
set -euo pipefail

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Expected env vars (set by deploy.yml when using default script):
#   REPO_URL  - Git URL to clone (e.g. https://github.com/owner/repo.git)
#   BRANCH    - Branch to deploy (e.g. main)
# Optional:
#   DEPLOY_DIR - Directory to clone into (default: /opt/boost-data-collector)
#
# Note: .env must be placed manually on the server at $DEPLOY_DIR/.env before deploying.

DEPLOY_DIR="${DEPLOY_DIR:-/opt/boost-data-collector}"

if [[ -z "${REPO_URL:-}" || -z "${BRANCH:-}" ]]; then
  log "ERROR: REPO_URL and BRANCH must be set."
  exit 1
fi

command -v git  >/dev/null 2>&1 || { log "ERROR: git is not installed.";  exit 1; }
command -v make >/dev/null 2>&1 || { log "ERROR: make is not installed."; exit 1; }

if [[ -d "$DEPLOY_DIR/.git" ]]; then
  log "Pulling latest in $DEPLOY_DIR..."
  git -C "$DEPLOY_DIR" fetch origin
  git -C "$DEPLOY_DIR" checkout "$BRANCH"
  git -C "$DEPLOY_DIR" reset --hard "origin/$BRANCH"
else
  log "Cloning $REPO_URL (branch: $BRANCH) into $DEPLOY_DIR..."
  mkdir -p "$(dirname "$DEPLOY_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$DEPLOY_DIR"
fi

if [[ ! -f "$DEPLOY_DIR/.env" ]]; then
  log "ERROR: .env not found. Place .env manually in $DEPLOY_DIR before deploying."
  exit 1
fi

cd "$DEPLOY_DIR"

log "Stopping existing containers..."
make down || true

log "Building and starting stack..."
make build
make up

log "Deploy completed."
