#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
HOST="${TOKEN_BI_HOST:-0.0.0.0}"
PORT="${TOKEN_BI_PORT:-8787}"
PID_FILE="$PROJECT_ROOT/runtime/token_bi.pid"
LOG_DIR="$PROJECT_ROOT/runtime/logs"
LOG_FILE="$LOG_DIR/server.log"
LOCAL_HOSTNAME="$(scutil --get LocalHostName 2>/dev/null || true)"

mkdir -p "$LOG_DIR"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing virtual environment: $VENV_PYTHON" >&2
  echo "Run: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "Token BI is already running (PID $EXISTING_PID)."
    echo "Local: http://127.0.0.1:$PORT/dashboard"
    if [[ -n "$LOCAL_HOSTNAME" ]]; then
      echo "Fixed: http://$LOCAL_HOSTNAME.local:$PORT/dashboard"
    fi
    exit 0
  fi
  rm -f "$PID_FILE"
fi

cd "$PROJECT_ROOT"

nohup "$VENV_PYTHON" -m uvicorn app.main:app --app-dir "$PROJECT_ROOT" --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" >"$PID_FILE"

for _ in $(seq 1 20); do
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Token BI failed to start. Check log: $LOG_FILE" >&2
  exit 1
fi

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [[ -z "$LAN_IP" ]]; then
  LAN_IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
fi

echo "Token BI started."
echo "PID: $SERVER_PID"
echo "Log: $LOG_FILE"
echo "Local: http://127.0.0.1:$PORT/dashboard"
if [[ -n "$LOCAL_HOSTNAME" ]]; then
  echo "Fixed: http://$LOCAL_HOSTNAME.local:$PORT/dashboard"
fi
if [[ -n "$LAN_IP" ]]; then
  echo "LAN: http://$LAN_IP:$PORT/dashboard"
fi
