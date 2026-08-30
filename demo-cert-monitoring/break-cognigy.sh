#!/bin/sh
# Flips the Cognigy (chat-/voicebot) vendor-outage demo into "unhealthy" -
# live, in the same Customer-Care exporter as break-customer-care.sh, but
# via a separate state file (COGNIGY_STATE_FILE) so this can be shown alone
# or alongside the Chemnitz-VPN scenario.
#
# Story: a SaaS vendor we depend on (Cognigy.AI) is degraded - not our own
# infrastructure, not a security issue. On-prem telephony, agents and the
# Chemnitz VPN are all untouched; only the one cloud dependency fails.
# API latency spikes, intent recognition collapses, bot sessions drop
# toward zero - customers/calls still try the bot, they just fail through
# it (falling back to human agents in the real world, not modelled here).
#
# Run this from demo-cert-monitoring/ while the stack is up. Use
# fix-cognigy.sh to reverse it.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Cognigy vendor exporter to 'unhealthy' ..."
docker compose exec -T customer-care-metrics-exporter sh -c 'echo unhealthy > /tmp/cognigy-state'

echo ""
echo "==> Done. Within ~15-30s the Customer-Care Grafana dashboard shows:"
echo "      - 'Cognigy (Cloud) – API-Latenz & Bot-Sessions' latency spikes, sessions collapse"
echo "      - 'Cognigy – Intent-Erfolgsquote' drops into the red (<90%)"
echo "    On-prem telephony, agents and the Chemnitz VPN stay healthy - isolated vendor outage."
echo "    Grafana: http://localhost:\${GRAFANA_PORT:-3000} (dashboard 'Customer Care – Standortübersicht')"
