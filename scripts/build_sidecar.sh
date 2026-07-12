#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$PROJECT_ROOT/src-tauri/binaries"
CONTROL_TARGET="$TARGET_DIR/token-bi-control-aarch64-apple-darwin"
CONTROL_LAUNCHER_SOURCE="$PROJECT_ROOT/src-tauri/control_launcher.rs"

mkdir -p "$TARGET_DIR"

"$PROJECT_ROOT/.venv/bin/pyinstaller" "$PROJECT_ROOT/token-bi-backend.spec" --noconfirm
"$PROJECT_ROOT/.venv/bin/pyinstaller" "$PROJECT_ROOT/token-bi-control.spec" --noconfirm
rustc --edition=2021 -C opt-level=3 "$CONTROL_LAUNCHER_SOURCE" -o "$CONTROL_TARGET"
chmod +x "$CONTROL_TARGET"

echo "Built control launcher: $CONTROL_TARGET"
echo "Built control runtime: $PROJECT_ROOT/dist/token-bi-control"
echo "Built backend runtime: $PROJECT_ROOT/dist/token-bi-backend"
