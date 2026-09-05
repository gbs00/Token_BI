#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "缺少项目 Python 环境，未执行任何进程清理。" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
exec "$VENV_PYTHON" -m scripts.control_cli --stop-dev control
