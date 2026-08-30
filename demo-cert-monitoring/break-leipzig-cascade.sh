#!/bin/sh
# Triggers the cascading Leipzig-internet-outage demo scenario, live: the
# "Internet-Anbindung" monitor goes offline first (root cause), then -
# after a short, visible delay - "Netzwerk (LAN)" and "WLAN" degrade too,
# and one Incident ends up linked to all three. Unlike every other live
# scenario in this demo, this one deliberately touches multiple monitors
# from a single cause instead of exactly one.
#
# Uses three Leipzig monitors no other live scenario touches (Internet-
# Anbindung, Netzwerk (LAN), WLAN), so it can't collide with anything.
#
# Requires OneUptime to be up and already seeded (./seed-oneuptime.sh).
# Run from demo-cert-monitoring/. Takes ~15s (the staged cascade).
# Reverse with ./fix-leipzig-cascade.sh.
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

echo "==> Triggering the cascading Leipzig-internet-outage scenario ..."
python3 scripts/cascading_incident.py break

echo ""
echo "==> Done. The IT-Services / Leipzig status pages show:"
echo "      - \"Internet-Anbindung\" offline (root cause)"
echo "      - \"Netzwerk (LAN)\" and \"WLAN\" degraded (Folgeschäden)"
echo "      - One incident \"Internetausfall mit Kettenreaktion (Standort Leipzig)\""
echo "    OneUptime: $OU_BASE (see .oneuptime-demo-summary for the exact URL)"
echo "    Recover with: ./fix-leipzig-cascade.sh"
