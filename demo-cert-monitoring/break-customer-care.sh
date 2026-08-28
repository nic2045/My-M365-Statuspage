#!/bin/sh
# Flips the Customer-Care demo into "unhealthy": the synthetic metrics
# exporter degrades the Chemnitz site's S2S VPN link into the Leipzig
# datacenter hard - packet loss, bad VoIP quality (MOS), bandwidth
# collapse - and the Avaya ACD queue backs up, all live in the
# "Customer Care - Standortübersicht (Technical Owner)" Grafana
# dashboard. No OneUptime/status-page involvement - this is the
# technical-owner side only.
#
# Run this from demo-cert-monitoring/ while the stack is up. Use
# fix-customer-care.sh to reverse it.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Customer-Care metrics exporter to 'unhealthy' ..."
docker compose exec -T customer-care-metrics-exporter sh -c 'echo unhealthy > /tmp/customer-care-state'

echo ""
echo "==> Done. Within ~15-30s the Grafana dashboard shows:"
echo "      - Deutschlandkarte: Chemnitz-Marker springt auf rot (VPN down)"
echo "      - Bandbreitenauslastung/MOS-Score/Latenz-Tabellen: Chemnitz fällt auf"
echo "      - Warteschlange & Wartezeit steigen an, Standorte mit VPN-Störung: 1"
echo "    Grafana: http://localhost:\${GRAFANA_PORT:-3000} (Dashboard 'Customer Care - Standortübersicht')"
