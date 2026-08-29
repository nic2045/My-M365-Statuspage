#!/bin/sh
# Flips the Standort-Leipzig LAN demo into "unhealthy": one access switch
# (Access-Switch Vertrieb-2) drops offline - live, in the already-running
# Grafana dashboard "Standort Leipzig - Netzwerk-Topologie".
#
# Run this from demo-cert-monitoring/ while the stack is up. Use
# fix-leipzig-network.sh to reverse it.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Leipzig network metrics exporter to 'unhealthy' ..."
docker compose exec -T leipzig-network-metrics-exporter sh -c 'echo unhealthy > /tmp/leipzig-network-state'

echo ""
echo "==> Done. Within ~15-30s the Grafana dashboard shows:"
echo "      - Access-Switch Vertrieb-2 offline (Node-Graph turns red, uplink drops)"
echo "      - 'Geräte offline' stat -> 1"
echo "    Grafana: http://localhost:\${GRAFANA_PORT:-3000} (dashboard 'Standort Leipzig - Netzwerk-Topologie')"
