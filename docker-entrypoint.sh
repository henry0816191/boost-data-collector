#!/bin/sh
set -e
# Ensure mounted dirs are writable by appuser (volumes are often root-owned)
chown -R appuser:appuser /app/workspace /app/logs 2>/dev/null || true
[ -d /app/celerybeat ] && chown -R appuser:appuser /app/celerybeat 2>/dev/null || true
exec gosu appuser "$@"
