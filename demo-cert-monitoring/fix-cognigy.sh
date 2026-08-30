#!/bin/sh
# Reverses break-cognigy.sh: flips the Cognigy vendor exporter state back
# to healthy, live.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Cognigy vendor exporter back to 'healthy' ..."
docker compose exec -T customer-care-metrics-exporter sh -c 'rm -f /tmp/cognigy-state'

echo ""
echo "==> Done. The Cognigy API/bot metrics recover within ~15-30s."
