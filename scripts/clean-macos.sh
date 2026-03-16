#!/usr/bin/env bash
# Remove macOS AppleDouble (._*) resource-fork files.
# These are created automatically by macOS on external/network volumes and
# cause Docker build errors ("failed to xattr … operation not permitted").
#
# Usage: ./scripts/clean-macos.sh [root-dir]
#   root-dir defaults to the project root (parent of this script's directory).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${1:-$(cd "$SCRIPT_DIR/.." && pwd)}"

echo "Scanning for macOS ._* files under: $ROOT"
COUNT=$(find "$ROOT" -name '._*' -not -path '*/.git/*' 2>/dev/null | wc -l | tr -d ' ')

if [ "$COUNT" -eq 0 ]; then
    echo "No ._* files found. Nothing to clean."
    exit 0
fi

find "$ROOT" -name '._*' -not -path '*/.git/*' -delete 2>/dev/null
echo "Removed $COUNT ._* file(s)."
