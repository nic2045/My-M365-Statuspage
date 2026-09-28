#!/bin/sh
# Flips the container-platform exporter's checkout-2 pod into a
# CrashLoopBackOff state: restart counter climbs, the pod goes
# not-Ready, its deployment drops from 3/3 to 2/3 available replicas -
# live, in the already-running Grafana dashboard "Container-Plattform -
# Kubernetes-Cluster (Platform-Team)".
#
# Also creates a real OneUptime incident ("Container-Plattform |
# CrashLoopBackOff (checkout-2)") on the Container-Plattform monitor,
# attached to the same "IT-Betrieb On-Call" policy as the other
# scenarios in this demo - so the employee notification (status page +
# subscriber email via Mailpit) and the On-Call impact show up for
# real. Skipped (with a note) if OneUptime isn't set up.
#
# Run this from demo-cert-monitoring/ while the stack is up. Use
# fix-container-platform.sh to reverse it.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the container-platform exporter's checkout-2 pod to 'crashloop' ..."
docker compose exec -T container-platform-metrics-exporter sh -c 'echo crashloop > /tmp/container-platform-state'

echo ""
echo "==> Done. Within ~15-30s the Grafana dashboard shows:"
echo "      - 'Pods nicht bereit' -> 1, 'Container-Neustarts' climbing"
echo "      - Deployments-Tabelle: checkout 2/3 verfügbar (frontend/catalog/search unverändert)"
echo "    Grafana: http://localhost:\${GRAFANA_PORT:-3000} (dashboard 'Container-Plattform - Kubernetes-Cluster')"

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
if [ -f "$ONEUPTIME_CONFIG" ]; then
  OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
  OU_PORT="${OU_PORT:-80}"
  if [ "$OU_PORT" = "80" ]; then
    OU_BASE="http://localhost"
  else
    OU_BASE="http://localhost:$OU_PORT"
  fi
  export OU_BASE
  echo ""
  echo "==> Triggering the matching OneUptime incident ..."
  python3 scripts/container_platform_incident.py break
  echo "    IT-Services: $OU_BASE (see .oneuptime-demo-summary for the exact URL)"
else
  echo ""
  echo "==> OneUptime not set up (no $ONEUPTIME_CONFIG) - skipping the OneUptime incident."
  echo "    Run ./start-demo.sh --with-oneuptime && ./seed-oneuptime.sh first to include it."
fi
