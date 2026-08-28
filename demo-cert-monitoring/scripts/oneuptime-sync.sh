#!/bin/sh
# Bridges Prometheus (internal probes) to OneUptime (public status page).
#
# For every target in DEMO_TARGET_URLS with a matching entry (by position)
# in ONEUPTIME_HEARTBEAT_URLS, this loop asks Prometheus whether the last
# blackbox probe succeeded. If yes, it pings the OneUptime "Incoming
# Request" / "Heartbeat" monitor URL, which OneUptime uses to derive
# up/down state on the public status page.
#
# This keeps Prometheus/Grafana as the single source of truth: OneUptime
# never probes the targets itself, it just reflects what Prometheus saw.
#
# If ONEUPTIME_HEARTBEAT_URLS is empty, the loop logs that and exits 0 -
# the rest of the demo (Prometheus + Grafana) works fine without it.
set -eu

PROM_URL="${PROM_URL:-http://prometheus:9090}"
INTERVAL="${SYNC_INTERVAL_SECONDS:-60}"
TARGETS="${DEMO_TARGET_URLS:-}"
HEARTBEATS="${ONEUPTIME_HEARTBEAT_URLS:-}"

if [ -z "$HEARTBEATS" ]; then
  echo "[oneuptime-sync] ONEUPTIME_HEARTBEAT_URLS not set - nothing to sync, exiting."
  echo "[oneuptime-sync] Prometheus/Grafana keep monitoring regardless."
  exit 0
fi

echo "[oneuptime-sync] installing curl + jq..."
apk add --no-cache curl jq >/dev/null

echo "[oneuptime-sync] starting sync loop, interval=${INTERVAL}s, prometheus=${PROM_URL}"

while true; do
  idx=0
  echo "$TARGETS" | tr ',' '\n' | while read -r target; do
    idx=$((idx + 1))
    target=$(echo "$target" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$target" ] && continue

    heartbeat=$(echo "$HEARTBEATS" | cut -d',' -f"$idx")
    heartbeat=$(echo "$heartbeat" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    if [ -z "$heartbeat" ]; then
      echo "[oneuptime-sync] no heartbeat URL configured for target #$idx ($target), skipping"
      continue
    fi

    success=$(curl -s --max-time 5 "$PROM_URL/api/v1/query" \
      --data-urlencode "query=probe_success{instance=\"$target\"}" \
      | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")

    if [ "$success" = "1" ]; then
      echo "[oneuptime-sync] $target UP -> pinging OneUptime heartbeat"
      curl -s -o /dev/null --max-time 5 "$heartbeat" \
        || echo "[oneuptime-sync] WARN: heartbeat ping failed for $target"
    else
      echo "[oneuptime-sync] $target DOWN or unknown -> not pinging (OneUptime marks it down after its own grace period)"
    fi
  done

  sleep "$INTERVAL"
done
