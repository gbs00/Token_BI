#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_ROOT/runtime/token_bi.pid"
PORT="${TOKEN_BI_PORT:-8787}"

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi

  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.5
  done

  kill -9 "$pid" 2>/dev/null || true
  sleep 0.5
  ! kill -0 "$pid" 2>/dev/null
}

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if stop_pid "$EXISTING_PID"; then
    rm -f "$PID_FILE"
    echo "Token BI stopped (PID $EXISTING_PID)."
    exit 0
  fi
  rm -f "$PID_FILE"
fi

PORT_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$PORT_PIDS" ]]; then
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    stop_pid "$pid" || true
  done <<< "$PORT_PIDS"
  rm -f "$PID_FILE"
  echo "Token BI stopped."
  exit 0
fi

echo "Token BI is not running."
