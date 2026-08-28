#!/bin/sh
# Reverses break-customer-care.sh: flips the Customer-Care metrics
# exporter back to healthy values, live.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Customer-Care metrics exporter back to 'healthy' ..."
docker compose exec -T customer-care-metrics-exporter sh -c 'rm -f /tmp/customer-care-state'

echo ""
echo "==> Done. The Chemnitz VPN link and ACD queue recover within ~15-30s."
