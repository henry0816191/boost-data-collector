#!/usr/bin/env bash
set -euo pipefail

# Expected env vars (set by deploy.yml when using default script):
#   REPO_URL  - Git URL to clone (e.g. https://github.com/owner/repo.git)
#   BRANCH    - Branch to deploy (e.g. main)
# Optional:
#   DEPLOY_DIR - Directory to clone into (default: /opt/boost-data-collector)

DEPLOY_DIR="${DEPLOY_DIR:-/opt/boost-data-collector}"

if [[ -z "${REPO_URL:-}" || -z "${BRANCH:-}" ]]; then
  echo "REPO_URL and BRANCH must be set."
  exit 1
fi

if [[ -d "$DEPLOY_DIR/.git" ]]; then
  echo "Pulling latest in $DEPLOY_DIR..."
  git -C "$DEPLOY_DIR" fetch origin
  git -C "$DEPLOY_DIR" checkout "$BRANCH"
  git -C "$DEPLOY_DIR" pull origin "$BRANCH"
else
  echo "Cloning $REPO_URL (branch: $BRANCH) into $DEPLOY_DIR..."
  mkdir -p "$(dirname "$DEPLOY_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

echo "Stopping existing containers..."
make down

echo "Building and starting stack..."
make build
make up

echo "Deploy completed."
