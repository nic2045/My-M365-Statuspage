#!/bin/sh
# Reverses break-demo.sh: regenerates demo-broken-site's certificate as
# healthy again, live, so you can watch the whole stack recover -
# mirroring the "Resolved" step of the test-incident walkthrough in
# README.md.
set -eu

cd "$(dirname "$0")"

DAYS="${1:-90}"

echo "==> Regenerating demo-broken-site's certificate with DEMO_CERT_DAYS_REMAINING=${DAYS} (healthy) ..."
docker compose run --rm -e DEMO_CERT_DAYS_REMAINING="$DAYS" demo-cert-init

echo "==> Restarting demo-broken-site so nginx picks up the new certificate ..."
docker compose restart demo-broken-site

echo ""
echo "==> Done. The site is healthy again - Prometheus/Grafana/oneuptime-sync"
echo "    will reflect recovery on their next cycle. Resolve the OneUptime"
echo "    incident manually (or let auto-recovery, if enabled, do it)."
