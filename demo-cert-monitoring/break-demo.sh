#!/bin/sh
# Flips demo-broken-site's certificate to already-expired, live, so you
# can watch the incident propagate through the whole stack while a demo
# is running:
#
#   blackbox_exporter (next scrape, <=15s) -> Prometheus
#     -> CertificateExpiringCritical alert fires (Prometheus /alerts,
#        also visible in Grafana's Prometheus-alerting view)
#     -> Grafana dashboard panels turn red (~30s panel refresh)
#     -> oneuptime-sync (next cycle, SYNC_INTERVAL_SECONDS) stops
#        pinging the demo heartbeat URL, if ONEUPTIME_DEMO_HEARTBEAT_URL
#        is set in .env
#     -> OneUptime marks the monitor down after its own "Not Received In
#        Minutes" grace period, and the public status page flips
#     -> a real incident is auto-created and, within a minute, OneUptime
#        sends an ACTUAL subscriber email via Mailpit (see
#        seed-oneuptime.sh) - a live version of mockups/benachrichtigung-*
#
# Run this from demo-cert-monitoring/ while the stack (docker compose up
# -d) is already running. Use fix-demo.sh to reverse it.
set -eu

cd "$(dirname "$0")"

DAYS="${1:--2}"

echo "==> Regenerating demo-broken-site's certificate with DEMO_CERT_DAYS_REMAINING=${DAYS} (expired) ..."
docker compose run --rm -e DEMO_CERT_DAYS_REMAINING="$DAYS" demo-cert-init

echo "==> Restarting demo-broken-site so nginx picks up the new certificate ..."
docker compose restart demo-broken-site

echo ""
echo "==> Done. The site is now serving an expired certificate."
echo "    Watch it propagate:"
echo "      - Prometheus:  http://localhost:\${PROMETHEUS_PORT:-9090}/alerts"
echo "      - Grafana:     http://localhost:\${GRAFANA_PORT:-3000} (dashboard updates within ~30s)"
echo "      - Sync log:    docker compose logs -f oneuptime-sync"
echo "      - OneUptime:   your monitor/status page (after its grace period)"
echo "      - Mailpit:     http://localhost:\${MAILPIT_WEB_PORT:-8025} (real email, ~5-6 min after breaking)"
