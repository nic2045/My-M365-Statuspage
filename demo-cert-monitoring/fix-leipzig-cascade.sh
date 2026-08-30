#!/bin/sh
# Reverses break-leipzig-cascade.sh: posts a resolution update, sets the
# incident to Resolved, and puts all three monitors ("Internet-Anbindung",
# "Netzwerk (LAN)", "WLAN") back to Operational.
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

echo "==> Resolving the cascading Leipzig-internet-outage scenario ..."
python3 scripts/cascading_incident.py fix

echo ""
echo "==> Done. The incident is Resolved, all three monitors are Operational again."
