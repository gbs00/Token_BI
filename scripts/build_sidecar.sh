#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$PROJECT_ROOT/src-tauri/binaries"
TARGET_BIN="$TARGET_DIR/token-bi-backend-aarch64-apple-darwin"

mkdir -p "$TARGET_DIR"

"$PROJECT_ROOT/.venv/bin/pyinstaller" "$PROJECT_ROOT/token-bi-backend.spec" --noconfirm
cp "$PROJECT_ROOT/dist/token-bi-backend" "$TARGET_BIN"
chmod +x "$TARGET_BIN"

echo "Built sidecar: $TARGET_BIN"
