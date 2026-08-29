#!/bin/sh
# Reverses break-leipzig-network.sh: flips the Leipzig network metrics
# exporter back to healthy values, live.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Leipzig network metrics exporter back to 'healthy' ..."
docker compose exec -T leipzig-network-metrics-exporter sh -c 'rm -f /tmp/leipzig-network-state'

echo ""
echo "==> Done. The switch stack recovers within ~15-30s."
