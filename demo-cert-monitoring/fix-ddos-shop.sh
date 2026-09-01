#!/bin/sh
# Reverses break-ddos-shop.sh: flips the Webshop metrics exporter state
# back to healthy, live.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Webshop metrics exporter back to 'healthy' ..."
docker compose exec -T webshop-metrics-exporter sh -c 'rm -f /tmp/webshop-state'

echo ""
echo "==> Done. The webshop metrics recover within ~15-30s."
