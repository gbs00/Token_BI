#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$PROJECT_ROOT/src-tauri/binaries"
CONTROL_TARGET="$TARGET_DIR/token-bi-control-aarch64-apple-darwin"
CONTROL_LAUNCHER_SOURCE="$PROJECT_ROOT/src-tauri/control_launcher.rs"

mkdir -p "$TARGET_DIR"

"$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/build_web_session.py"

"$PROJECT_ROOT/.venv/bin/pyinstaller" "$PROJECT_ROOT/token-bi.spec" --noconfirm
rustc --edition=2021 -C opt-level=3 -C strip=symbols "$CONTROL_LAUNCHER_SOURCE" -o "$CONTROL_TARGET"
chmod +x "$CONTROL_TARGET"

echo "Built control launcher: $CONTROL_TARGET"
echo "Built shared runtime: $PROJECT_ROOT/dist/token-bi-runtime"
