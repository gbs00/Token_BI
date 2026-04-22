#!/bin/zsh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
PORT="${1:-8787}"

cd "$PROJECT_ROOT"

./.venv/bin/python scripts/seed_demo_accounts.py
echo "Starting mock preview on http://127.0.0.1:${PORT}"
echo "Use TOKEN_BI_USE_MOCK_SCRAPER=true so the dashboard renders fake quota data."
TOKEN_BI_USE_MOCK_SCRAPER=true ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
