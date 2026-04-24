#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

"$PROJECT_ROOT/.venv/bin/pytest" -q
"$PROJECT_ROOT/.venv/bin/python" -m compileall app scripts tests
npm run app:build

APP_PATH="$PROJECT_ROOT/src-tauri/target/release/bundle/macos/Token BI.app"
DMG_PATH="$(find "$PROJECT_ROOT/src-tauri/target/release/bundle/dmg" -name 'Token BI_*.dmg' -maxdepth 1 -print | sort | tail -n 1)"

echo "Release artifacts:"
echo "App: $APP_PATH"
echo "DMG: $DMG_PATH"
echo "No upload or git push was performed."
