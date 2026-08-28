#!/bin/sh
# Starts the local demo control panel: a small page with one card per
# incident scenario (story, status, break/fix buttons) instead of
# driving break-*.sh/fix-*.sh from the terminal.
#
# Binds to 127.0.0.1 only - never reachable from the network. Runs in
# the foreground; stop with Ctrl+C.
set -eu

cd "$(dirname "$0")"

PORT="${CONTROL_PANEL_PORT:-7100}"

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR: python3 is required (only the standard library is used)." >&2
  exit 1
}

echo "==> Kontrollzentrum: http://localhost:$PORT"
echo "    Strg+C zum Beenden."
exec python3 scripts/control_panel_server.py
