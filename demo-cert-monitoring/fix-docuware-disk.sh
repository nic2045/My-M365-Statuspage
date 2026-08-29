#!/bin/sh
# Reverses break-docuware-disk.sh: flips the DocuWare metrics exporter's
# Dokumentenspeicher volume back to healthy values, live, and resolves
# the matching OneUptime incident (if OneUptime is set up).
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the DocuWare metrics exporter's Dokumentenspeicher volume back to 'healthy' ..."
docker compose exec -T docuware-metrics-exporter sh -c 'rm -f /tmp/docuware-disk-state'

echo ""
echo "==> Done. The volume usage recovers within ~15-30s."

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
if [ -f "$ONEUPTIME_CONFIG" ]; then
  OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
  OU_PORT="${OU_PORT:-80}"
  if [ "$OU_PORT" = "80" ]; then
    OU_BASE="http://localhost"
  else
    OU_BASE="http://localhost:$OU_PORT"
  fi
  export OU_BASE
  echo ""
  echo "==> Resolving the matching OneUptime incident ..."
  python3 scripts/docuware_disk_incident.py fix
fi
