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
