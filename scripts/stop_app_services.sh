#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

"$PROJECT_ROOT/scripts/stop_server.sh" || true
"$PROJECT_ROOT/scripts/stop_control_panel.sh" || true

# Close Chrome workers that Token BI launched with project-owned profiles.
pkill -f "$PROJECT_ROOT/runtime/contexts" 2>/dev/null || true

echo "Token BI app services stopped."
