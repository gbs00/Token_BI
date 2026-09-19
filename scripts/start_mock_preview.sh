#!/bin/zsh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
PORT="${1:-8899}"

cd "$PROJECT_ROOT"

exec ./.venv/bin/python scripts/preview_dashboard.py --host 127.0.0.1 --port "$PORT"
