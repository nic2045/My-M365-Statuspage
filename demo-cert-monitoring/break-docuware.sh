#!/bin/sh
# Flips the DocuWare-cluster demo into "unhealthy": the synthetic metrics
# exporter starts reporting MSSQL db2 down, WAF blocked-request spikes
# and slow IIS/APM response times - live, in the already-running
# Grafana dashboard "DocuWare - Cluster-Status (App-Owner)".
#
# This is independent of the DocuWare reachability heartbeat (the
# 🗂️ DocuWare monitor on the main status page): that one reflects the
# demo-docuware-site fixture, which stays reachable throughout - only
# the cluster's internal health degrades, matching the seeded major
# incident "DocuWare | Anmeldung in DocuWare nicht möglich" (site up,
# login broken).
#
# Run this from demo-cert-monitoring/ while the stack is up. Use
# fix-docuware.sh to reverse it.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the DocuWare cluster metrics exporter to 'unhealthy' ..."
docker compose exec -T docuware-metrics-exporter sh -c 'echo unhealthy > /tmp/docuware-state'

echo ""
echo "==> Done. Within ~15-30s the Grafana dashboard shows:"
echo "      - MSSQL-Cluster db2 down (Knotenstatus table, Knoten online stat)"
echo "      - WAF blocked-request spike"
echo "      - IIS/APM response times climbing"
echo "    Grafana: http://localhost:\${GRAFANA_PORT:-3000} (dashboard 'DocuWare - Cluster-Status')"
