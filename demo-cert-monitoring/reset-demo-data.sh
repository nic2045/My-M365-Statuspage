#!/bin/sh
# Wipes accumulated Prometheus metric history so graphs/dashboards start
# from zero again, while leaving every configuration untouched (targets,
# alert rules, Grafana dashboards/datasources, OneUptime monitors/status
# pages/on-call policies/etc. - none of that lives in this volume).
#
# Scope, deliberately: THIS SCRIPT ONLY TOUCHES PROMETHEUS. OneUptime's
# own accumulated history (incident timelines, logs, security events,
# alerts already fired) has no single "clear history, keep config" API
# call - it would need many individual deletes across several models,
# risking breaking the seeded structure this demo depends on. Not
# attempted here; ./seed-oneuptime.sh already re-converges OneUptime's
# structure on every run regardless, so re-running it after this script
# is the safe way to get a consistent, freshly-seeded state.
#
# Usage: ./reset-demo-data.sh
set -eu

cd "$(dirname "$0")"

echo "==> Stopping Prometheus ..."
docker compose stop prometheus >/dev/null

echo "==> Removing accumulated metric history (prometheus_data volume) ..."
docker compose rm -f prometheus >/dev/null
docker volume rm "$(basename "$(pwd)")_prometheus_data" >/dev/null 2>&1 \
  || docker volume rm demo-cert-monitoring_prometheus_data >/dev/null 2>&1 \
  || echo "    (volume already gone or named differently - continuing)"

echo "==> Starting Prometheus fresh ..."
docker compose up -d prometheus >/dev/null

echo ""
echo "==> Done. Prometheus starts collecting from zero - dashboards will"
echo "    look empty/flat for the first minute until new scrapes land."
echo "    Nothing configuration-related changed (targets, alert rules,"
echo "    Grafana, OneUptime all untouched)."
