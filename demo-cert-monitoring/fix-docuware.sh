#!/bin/sh
# Reverses break-docuware.sh: flips the DocuWare-cluster metrics exporter
# back to healthy values, live.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the DocuWare cluster metrics exporter back to 'healthy' ..."
docker compose exec -T docuware-metrics-exporter sh -c 'rm -f /tmp/docuware-state'

echo ""
echo "==> Done. The cluster metrics recover within ~15-30s."
