#!/bin/sh
# Flips the DocuWare cluster metrics exporter's "Dokumentenspeicher" SAN
# volume into a disk-full state: usage climbs into the 92-98% critical
# range, live, in the already-running Grafana dashboard "DocuWare -
# Cluster-Status (App-Owner)". Datenbank/Log volumes are unaffected -
# same isolated-blast-radius storytelling as the other DocuWare incidents
# in this exporter.
#
# Independent of break-docuware.sh (the MSSQL/WAF infrastructure
# incident) - the two use separate state files and can be demoed on
# their own or together.
#
# Also creates a real OneUptime incident ("DocuWare | Speicherplatz
# kritisch (Dokumentenspeicher)") on the DocuWare monitor, attached to
# the same "IT-Betrieb On-Call" policy as the other DocuWare incident -
# so the employee notification (status page + subscriber email via
# Mailpit) and the On-Call impact show up for real, not just as a
# Grafana metric. Skipped (with a note) if OneUptime isn't set up.
#
# Run this from demo-cert-monitoring/ while the stack is up. Use
# fix-docuware-disk.sh to reverse it.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the DocuWare metrics exporter's Dokumentenspeicher volume to 'full' ..."
docker compose exec -T docuware-metrics-exporter sh -c 'echo full > /tmp/docuware-disk-state'

echo ""
echo "==> Done. Within ~15-30s the Grafana dashboard shows:"
echo "      - 'Speicherplatz-Auslastung (SAN-Volumes)' - Dokumentenspeicher climbs into the red (>90%)"
echo "      - Datenbank/Log volumes stay in their normal range"
echo "    Grafana: http://localhost:\${GRAFANA_PORT:-3000} (dashboard 'DocuWare - Cluster-Status (App-Owner)')"

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
  echo "==> Triggering the matching OneUptime incident ..."
  python3 scripts/docuware_disk_incident.py break
  echo "    IT-Services: $OU_BASE (see .oneuptime-demo-summary for the exact URL)"
else
  echo ""
  echo "==> OneUptime not set up (no $ONEUPTIME_CONFIG) - skipping the OneUptime incident."
  echo "    Run ./start-demo.sh --with-oneuptime && ./seed-oneuptime.sh first to include it."
fi
