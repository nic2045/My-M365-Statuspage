#!/bin/sh
# Reverses break-printer.sh: sets "Kurzfristige Wartung - Drucker
# (Hauptgebäude)" to Completed, so it becomes another finished maintenance
# entry on the Standort-Leipzig status page instead of an open one.
set -eu

cd "$(dirname "$0")"

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
[ -f "$ONEUPTIME_CONFIG" ] || {
  echo "ERROR: $ONEUPTIME_CONFIG not found - OneUptime isn't set up yet." >&2
  exit 1
}

OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
OU_PORT="${OU_PORT:-80}"
if [ "$OU_PORT" = "80" ]; then
  OU_BASE="http://localhost"
else
  OU_BASE="http://localhost:$OU_PORT"
fi
export OU_BASE

echo "==> Completing the printer-maintenance-process scenario ..."
python3 scripts/printer_maintenance.py fix

echo ""
echo "==> Done. \"Kurzfristige Wartung - Drucker (Hauptgebäude)\" is now Completed."
