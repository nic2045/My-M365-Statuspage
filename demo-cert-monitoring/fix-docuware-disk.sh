#!/bin/sh
# Reverses break-docuware-disk.sh: flips the DocuWare metrics exporter's
# Dokumentenspeicher volume back to healthy values, live.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the DocuWare metrics exporter's Dokumentenspeicher volume back to 'healthy' ..."
docker compose exec -T docuware-metrics-exporter sh -c 'rm -f /tmp/docuware-disk-state'

echo ""
echo "==> Done. The volume usage recovers within ~15-30s."
