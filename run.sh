#!/usr/bin/env bash
set -euo pipefail

# Both launchers use the same Python CLI: --dev automatically detects network IPs.
# Resolve the project directory so this also works from another working directory.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  printf 'Error: uv is required to run Moviebox.\n' >&2
  exit 1
fi

exec uv run python main.py "$@"
