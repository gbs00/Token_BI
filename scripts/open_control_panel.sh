#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
CONTROL_HOST="${TOKEN_BI_CONTROL_HOST:-127.0.0.1}"
CONTROL_PORT="${TOKEN_BI_CONTROL_PORT:-8790}"
PID_FILE="$PROJECT_ROOT/runtime/control_panel.pid"
LOG_DIR="$PROJECT_ROOT/runtime/logs"
LOG_FILE="$LOG_DIR/control_panel.log"
CONTROL_URL="http://$CONTROL_HOST:$CONTROL_PORT/"

mkdir -p "$LOG_DIR"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing virtual environment: $VENV_PYTHON" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    open "$CONTROL_URL"
    echo "Control panel already running: $CONTROL_URL"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

nohup "$VENV_PYTHON" "$PROJECT_ROOT/scripts/control_panel.py" >"$LOG_FILE" 2>&1 &
CONTROL_PID=$!
echo "$CONTROL_PID" >"$PID_FILE"

for _ in $(seq 1 20); do
  if lsof -nP -iTCP:"$CONTROL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.3
done

open "$CONTROL_URL"
echo "Control panel started: $CONTROL_URL"
