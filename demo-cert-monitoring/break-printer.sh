#!/bin/sh
# Triggers the printer-maintenance-process demo scenario (#148), live:
# OneUptime gets a new Scheduled Maintenance "Kurzfristige Wartung -
# Drucker (Hauptgebäude)" on short notice, visible immediately on the
# Standort-Leipzig status page - the process this demonstrates is
# "Drucker meldet Störung -> Techniker stellt Wartung ein -> Mitarbeiter
# bekommt durch Statuspage Info". The printer monitor itself is never
# touched: it stays Operational throughout, showing that a Scheduled
# Maintenance only announces upcoming impact, it doesn't itself cause one
# - "Drucker ist bis zur Wartung nicht eingeschränkt".
#
# Complements (doesn't replace) the static "next Friday" printer
# maintenance seed-oneuptime.sh always creates - same idea as the live
# security-incident scenario sitting alongside its resolved historical
# incidents (see break-security.sh): a distinct, separately named entry.
#
# Requires OneUptime to be up and already seeded (./seed-oneuptime.sh).
# Run from demo-cert-monitoring/. Reverse with ./fix-printer.sh.
set -eu

cd "$(dirname "$0")"

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
[ -f "$ONEUPTIME_CONFIG" ] || {
  echo "ERROR: $ONEUPTIME_CONFIG not found - OneUptime isn't set up yet." >&2
  echo "       Run: ./start-demo.sh --with-oneuptime && ./seed-oneuptime.sh" >&2
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

echo "==> Triggering the printer-maintenance-process scenario ..."
python3 scripts/printer_maintenance.py break

echo ""
echo "==> Done. Within a few seconds the Standort-Leipzig status page shows:"
echo "      - New scheduled maintenance \"Kurzfristige Wartung - Drucker (Hauptgebäude)\""
echo "      - \"Drucker (Hauptgebäude)\" stays Operational - no restriction yet"
echo "    Standort Leipzig: $OU_BASE (see .oneuptime-demo-summary for the exact URL)"
echo "    Complete the maintenance with: ./fix-printer.sh"
