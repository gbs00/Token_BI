#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 复用唯一启动入口；启动失败时不再打开一个不可访问的页面。
"$SCRIPT_DIR/start_control_panel.sh"
open "http://${TOKEN_BI_CONTROL_HOST:-127.0.0.1}:${TOKEN_BI_CONTROL_PORT:-8790}/"
