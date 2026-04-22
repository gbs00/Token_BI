#!/bin/zsh

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: ./scripts/open_account_login.sh <account_id> [url]"
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
ACCOUNT_ID="$1"
TARGET_URL="${2:-https://chatgpt.com/#usage}"
USER_DATA_DIR="$PROJECT_ROOT/runtime/contexts/$ACCOUNT_ID"
CHROME_APP="Google Chrome"
LOG_FILE="$PROJECT_ROOT/runtime/logs/login-${ACCOUNT_ID}.log"
DEBUG_PORT="${3:-9222}"

mkdir -p "$USER_DATA_DIR"
mkdir -p "$PROJECT_ROOT/runtime/logs"

open -na "$CHROME_APP" --args \
  "--remote-debugging-port=$DEBUG_PORT" \
  "--user-data-dir=$USER_DATA_DIR" \
  --new-window \
  --no-first-run \
  --no-default-browser-check \
  "$TARGET_URL" \
  >"$LOG_FILE" 2>&1 &

sleep 1
osascript -e 'tell application "Google Chrome" to activate' >/dev/null 2>&1 || true
