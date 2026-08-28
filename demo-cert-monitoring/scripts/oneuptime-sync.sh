#!/bin/sh
# Bridges Prometheus (internal probes) to OneUptime (public status page).
#
# For every target in DEMO_TARGET_URLS with a matching entry (by position)
# in ONEUPTIME_HEARTBEAT_URLS, this loop asks Prometheus whether the last
# blackbox probe succeeded. If yes, it pings the OneUptime "Incoming
# Request" / "Heartbeat" monitor URL, which OneUptime uses to derive
# up/down state on the public status page.
#
# Optionally also syncs the fixed demo-broken-site fixture (see
# ../break-demo.sh) via ONEUPTIME_DEMO_HEARTBEAT_URL - for that target,
# a healthy ping additionally requires the certificate not be critically
# close to expiry (DEMO_CERT_CRITICAL_DAYS, matches the
# CertificateExpiringCritical alert threshold), so breaking the demo
# cert stops the heartbeat even though the site itself stays reachable
# (insecure_skip_verify is used for that fixture - see blackbox.yml).
#
# demo-docuware-site is NOT synced here on purpose: its OneUptime-facing
# status follows the seeded DocuWare major incident (login broken, site
# still reachable), not plain reachability - see seed_oneuptime.py. Its
# cluster-internal health (WAF/MSSQL/IIS/...) is a separate story, shown
# only in Grafana and toggled by ../break-docuware.sh / ../fix-docuware.sh.
#
# This keeps Prometheus/Grafana as the single source of truth: OneUptime
# never probes the targets itself, it just reflects what Prometheus saw.
#
# If neither ONEUPTIME_HEARTBEAT_URLS nor ONEUPTIME_DEMO_HEARTBEAT_URL is
# set, the loop logs that and exits 0 - the rest of the demo
# (Prometheus + Grafana) works fine without it.
set -eu

PROM_URL="${PROM_URL:-http://prometheus:9090}"
INTERVAL="${SYNC_INTERVAL_SECONDS:-60}"
TARGETS="${DEMO_TARGET_URLS:-}"
HEARTBEATS="${ONEUPTIME_HEARTBEAT_URLS:-}"
DEMO_HEARTBEAT="${ONEUPTIME_DEMO_HEARTBEAT_URL:-}"
CERT_CRITICAL_DAYS="${DEMO_CERT_CRITICAL_DAYS:-3}"
DEMO_TARGET="https://demo-broken-site"

if [ -z "$HEARTBEATS" ] && [ -z "$DEMO_HEARTBEAT" ]; then
  echo "[oneuptime-sync] Neither ONEUPTIME_HEARTBEAT_URLS nor ONEUPTIME_DEMO_HEARTBEAT_URL is set - nothing to sync, exiting."
  echo "[oneuptime-sync] Prometheus/Grafana keep monitoring regardless."
  exit 0
fi

echo "[oneuptime-sync] installing curl + jq..."
apk add --no-cache curl jq >/dev/null

# Pings $heartbeat for $target only if it's reachable (probe_success==1)
# and, when $require_cert_ok=1, its cert isn't within
# CERT_CRITICAL_DAYS of expiry (or already expired).
#
# $4 is the Prometheus label selector and defaults to instance="$target".
# The demo fixture needs an explicit one: prometheus.yml relabels its
# instance to a human-readable string, so selecting it by its target URL
# matches nothing and jq's "// 0" fallback would report a healthy fixture
# as permanently down. Its demo_fixture="true" label is stable.
ping_if_healthy() {
  target="$1"
  heartbeat="$2"
  require_cert_ok="$3"
  selector="${4:-instance=\"$target\"}"

  success=$(curl -s --max-time 5 "$PROM_URL/api/v1/query" \
    --data-urlencode "query=probe_success{$selector}" \
    | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")

  healthy="$success"

  if [ "$require_cert_ok" = "1" ] && [ "$success" = "1" ]; then
    cert_days=$(curl -s --max-time 5 "$PROM_URL/api/v1/query" \
      --data-urlencode "query=(probe_ssl_earliest_cert_expiry{$selector} - time()) / 86400" \
      | jq -r '.data.result[0].value[1] // "-999"' 2>/dev/null || echo "-999")

    if awk -v d="$cert_days" -v t="$CERT_CRITICAL_DAYS" 'BEGIN{exit !(d < t)}'; then
      echo "[oneuptime-sync] $target reachable but cert expires in ${cert_days} days (< ${CERT_CRITICAL_DAYS}) -> treating as unhealthy"
      healthy=0
    fi
  fi

  if [ "$healthy" = "1" ]; then
    echo "[oneuptime-sync] $target UP -> pinging OneUptime heartbeat"
    curl -s -o /dev/null --max-time 5 "$heartbeat" \
      || echo "[oneuptime-sync] WARN: heartbeat ping failed for $target"
  else
    echo "[oneuptime-sync] $target DOWN/unhealthy -> not pinging (OneUptime marks it down after its own grace period)"
  fi
}

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

    ping_if_healthy "$target" "$heartbeat" "0"
  done

  if [ -n "$DEMO_HEARTBEAT" ]; then
    ping_if_healthy "$DEMO_TARGET" "$DEMO_HEARTBEAT" "1" 'demo_fixture="true"'
  fi

  sleep "$INTERVAL"
done
