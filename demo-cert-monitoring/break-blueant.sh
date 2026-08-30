#!/bin/sh
# Triggers the Blueant demo scenario, live: OneUptime's "Blueant" monitor
# flips to Offline and a real Incident ("Blueant nicht erreichbar") appears
# on the IT-Services status page.
#
# Story: an ad-hoc, unplanned Blueant outage - deliberately the opposite of
# the only other Blueant disruption in this demo (the always-"currently
# happening" Patchday maintenance in seed_oneuptime.py), which is planned
# and expected. This one is a genuine, unannounced incident, independent of
# Patchday and triggerable on its own.
#
# Requires OneUptime to be up and already seeded (./seed-oneuptime.sh).
# Run from demo-cert-monitoring/. Reverse with ./fix-blueant.sh.
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

echo "==> Triggering the Blueant scenario ..."
python3 scripts/blueant_incident.py break

echo ""
echo "==> Done. Within a few seconds the IT-Services status page shows:"
echo "      - \"Blueant\" offline"
echo "      - New incident \"Blueant nicht erreichbar\""
echo "    IT-Services: $OU_BASE (see .oneuptime-demo-summary for the exact URL)"
echo "    Recover with: ./fix-blueant.sh"
