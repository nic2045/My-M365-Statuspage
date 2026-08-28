#!/bin/sh
# One-shot launcher for the whole certificate-/availability-monitoring demo.
#
# Brings the stack up from a cold machine and doesn't return until the
# pieces actually answer - so a demo never starts against a Grafana that
# is still booting or a Prometheus that hasn't scraped anything yet.
#
# Flow:
#   1. preflight  - docker present, daemon reachable, host ports free
#   2. .env       - created from .env.example on first run
#   3. core stack - Prometheus + blackbox_exporter + Grafana + the
#                   demo-broken-site fixture (docker-compose.yml)
#   4. readiness  - wait for Prometheus/Grafana HTTP + first successful probe
#   5. OneUptime  - only with --with-oneuptime (separate, much heavier stack),
#                   including seeding a demo account, monitors and a ready
#                   public status page (skip with --no-seed)
#   6. summary    - URLs and the next step of the walkthrough
#
# Usage:
#   ./start-demo.sh                    # core stack only (fast, recommended)
#   ./start-demo.sh --with-oneuptime   # additionally clone+start OneUptime and seed it
#   ./start-demo.sh --with-oneuptime --no-seed   # ... but leave OneUptime empty
#   ./start-demo.sh --break            # core stack, then trigger the cert incident
#   ./start-demo.sh --help
#
# Reverse the incident with ./fix-demo.sh, tear everything down with
# ./stop-demo.sh.
set -eu

cd "$(dirname "$0")"

WITH_ONEUPTIME=0
BREAK_AFTER=0
SEED=1

usage() {
  # Print the leading comment block (everything until the first
  # non-comment line), so the help text can never drift out of sync
  # with a fixed line range.
  awk 'NR>1 { if (/^#/) { sub(/^# ?/, ""); print } else { exit } }' "$0"
  exit "${1:-0}"
}

for arg in "$@"; do
  case "$arg" in
    --with-oneuptime) WITH_ONEUPTIME=1 ;;
    --no-seed)        SEED=0 ;;
    --break)          BREAK_AFTER=1 ;;
    -h|--help)        usage 0 ;;
    *) echo "ERROR: unknown option '$arg' (try --help)" >&2; exit 2 ;;
  esac
done

# Reads a single key from .env without sourcing it (values may contain
# characters that would be re-interpreted by the shell).
env_value() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2-
}

# True if something is already listening on the given TCP port.
port_taken() {
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

# Polls $1 (URL) until it answers, up to $2 seconds. Returns 1 on timeout.
wait_for_http() {
  url="$1"; deadline="$2"; label="$3"
  command -v curl >/dev/null 2>&1 || { echo "    (curl missing - skipping $label readiness check)"; return 0; }
  waited=0
  while [ "$waited" -lt "$deadline" ]; do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      echo "    $label is up (after ${waited}s)"
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  echo "    WARNING: $label did not answer within ${deadline}s ($url)" >&2
  return 1
}

# ── 1. Preflight ────────────────────────────────────────────────────────────
echo "==> Preflight ..."
command -v docker >/dev/null 2>&1 || {
  echo "ERROR: docker not found. Install Docker Desktop / Docker Engine first." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "ERROR: docker daemon not reachable. Start Docker and retry." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "ERROR: 'docker compose' (v2) not available." >&2
  exit 1
}
echo "    docker OK"

# ── 2. .env ─────────────────────────────────────────────────────────────────
if [ -f .env ]; then
  echo "==> .env exists, leaving it untouched."
else
  echo "==> No .env found - creating it from .env.example ..."
  cp .env.example .env
  echo "    Created .env with defaults. Edit DEMO_TARGET_URLS / GRAFANA_ADMIN_PASSWORD"
  echo "    and re-run if you want different values."
fi

GRAFANA_PORT="$(env_value GRAFANA_PORT)";              GRAFANA_PORT="${GRAFANA_PORT:-3000}"
PROMETHEUS_PORT="$(env_value PROMETHEUS_PORT)";        PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
BLACKBOX_PORT="$(env_value BLACKBOX_EXPORTER_PORT)";   BLACKBOX_PORT="${BLACKBOX_PORT:-9115}"
BROKEN_SITE_PORT="$(env_value DEMO_BROKEN_SITE_PORT)"; BROKEN_SITE_PORT="${BROKEN_SITE_PORT:-8443}"
MAILPIT_WEB_PORT="$(env_value MAILPIT_WEB_PORT)";      MAILPIT_WEB_PORT="${MAILPIT_WEB_PORT:-8025}"

# Ports already bound by *our own* running containers are fine - compose
# will reuse them. Only warn about ports held by something else.
echo "==> Checking host ports ..."
for spec in "$GRAFANA_PORT:Grafana" "$PROMETHEUS_PORT:Prometheus" \
            "$BLACKBOX_PORT:blackbox_exporter" "$BROKEN_SITE_PORT:demo-broken-site"; do
  p="${spec%%:*}"; name="${spec#*:}"
  # 'ps -q' lists container IDs only - plain 'ps' prints a header row even
  # when nothing runs, which would make this test always true.
  if port_taken "$p" && [ -z "$(docker compose ps -q --status running 2>/dev/null)" ]; then
    echo "    WARNING: port $p ($name) is already in use by another process." >&2
    echo "             Change the port in .env or stop that process." >&2
  fi
done

# ── 3. Core stack ───────────────────────────────────────────────────────────
echo "==> Starting core stack (Prometheus, blackbox_exporter, Grafana, demo fixture) ..."
docker compose up -d --remove-orphans

# ── 4. Readiness ────────────────────────────────────────────────────────────
echo "==> Waiting for services to answer ..."
wait_for_http "http://localhost:$PROMETHEUS_PORT/-/ready" 90 "Prometheus" || true
wait_for_http "http://localhost:$GRAFANA_PORT/api/health" 90 "Grafana"    || true

# A green HTTP endpoint isn't enough for a demo - Prometheus must also have
# actually scraped the blackbox targets at least once.
if command -v curl >/dev/null 2>&1; then
  echo "    Waiting for the first blackbox probe results ..."
  waited=0
  while [ "$waited" -lt 60 ]; do
    n=$(curl -fsS --max-time 3 \
          "http://localhost:$PROMETHEUS_PORT/api/v1/query?query=count(probe_success)" 2>/dev/null \
        | sed -n 's/.*"value":\[[^,]*,"\([0-9]*\)".*/\1/p')
    if [ -n "${n:-}" ] && [ "$n" -gt 0 ] 2>/dev/null; then
      echo "    $n probe target(s) reporting."
      break
    fi
    sleep 3
    waited=$((waited + 3))
  done
  [ "$waited" -lt 60 ] || echo "    WARNING: no probe results yet - check 'docker compose logs blackbox_exporter'" >&2
fi

# ── 5. OneUptime (optional) ─────────────────────────────────────────────────
if [ "$WITH_ONEUPTIME" = "1" ]; then
  echo ""
  echo "==> Setting up self-hosted OneUptime (separate, heavy stack) ..."
  echo "    First run clones OneUptime and pulls ~15 service images - this takes a while."
  # setup.sh --start does the clone, the config.env generation AND the
  # 'docker compose --env-file config.env up -d'. Deliberately not
  # duplicating the start command here - setup.sh stays the single place
  # that knows how OneUptime is launched.
  ./oneuptime-selfhosted/setup.sh --start

  ONEUPTIME_DIR="oneuptime-selfhosted/oneuptime"
  ONEUPTIME_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_DIR/config.env" | tail -1 | cut -d= -f2-)
  ONEUPTIME_PORT="${ONEUPTIME_PORT:-80}"
  # Port 80 is implicit in a URL - printing "localhost:80" just looks broken.
  if [ "$ONEUPTIME_PORT" = "80" ]; then
    ONEUPTIME_URL="http://localhost"
  else
    ONEUPTIME_URL="http://localhost:$ONEUPTIME_PORT"
  fi
  echo "==> Waiting for OneUptime (first boot runs DB migrations - can take several minutes) ..."
  if wait_for_http "$ONEUPTIME_URL" 600 "OneUptime"; then
    if [ "$SEED" = "1" ]; then
      echo ""
      # Seeding needs a reachable OneUptime, so it only runs once the wait
      # above succeeded. It is idempotent, so re-running start-demo.sh is safe.
      ./seed-oneuptime.sh
      SEEDED=1
    fi
  else
    echo "    Still booting? Follow along with:" >&2
    echo "      cd $ONEUPTIME_DIR && docker compose --env-file config.env logs -f" >&2
    echo "    Once it answers, run ./seed-oneuptime.sh to create the demo data." >&2
  fi
fi

# ── 6. Incident fixture (optional) ──────────────────────────────────────────
if [ "$BREAK_AFTER" = "1" ]; then
  echo ""
  echo "==> Triggering the certificate incident (--break) ..."
  ./break-demo.sh
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo " Demo is up."
echo "================================================================"
echo "  Grafana .......... http://localhost:$GRAFANA_PORT"
echo "                     user: $(env_value GRAFANA_ADMIN_USER || echo admin)"
echo "                     pass: (GRAFANA_ADMIN_PASSWORD in .env)"
echo "  Prometheus ....... http://localhost:$PROMETHEUS_PORT"
echo "  Alerts ........... http://localhost:$PROMETHEUS_PORT/alerts"
echo "  blackbox ......... http://localhost:$BLACKBOX_PORT"
echo "  Demo fixture ..... https://localhost:$BROKEN_SITE_PORT (self-signed on purpose)"
echo "  Mailpit .......... http://localhost:$MAILPIT_WEB_PORT (live email demo inbox)"
if [ "$WITH_ONEUPTIME" = "1" ]; then
  echo "  OneUptime ........ ${ONEUPTIME_URL:-http://localhost}"
  if [ "${SEEDED:-0}" = "1" ] && [ -f .oneuptime-demo-summary ]; then
    echo "                     login: demo@example.com / DemoDemo123!"
    echo "  Zertifikate ...... ${ONEUPTIME_URL:-http://localhost}/status-page/$(python3 -c 'import json;print(json.load(open(".oneuptime-demo-summary"))["statusPageId"])' 2>/dev/null)"
    echo "  IT-Services ...... ${ONEUPTIME_URL:-http://localhost}/status-page/$(python3 -c 'import json;print(json.load(open(".oneuptime-demo-summary"))["itServiceStatusPageId"])' 2>/dev/null)"
    echo "  Standort Leipzig . ${ONEUPTIME_URL:-http://localhost}/status-page/$(python3 -c 'import json;print(json.load(open(".oneuptime-demo-summary"))["leipzigStatusPageId"])' 2>/dev/null)"
  else
    echo "                     not seeded - run ./seed-oneuptime.sh to create"
    echo "                     the demo account, monitors and status page."
  fi
fi
echo ""
if [ "$BREAK_AFTER" = "1" ]; then
  echo "  Incident is LIVE - the fixture serves an expired certificate."
  echo "  Recover with:  ./fix-demo.sh"
else
  echo "  Next: ./break-demo.sh   trigger the certificate incident live"
  echo "        ./fix-demo.sh     recover from it"
fi
echo "        ./stop-demo.sh    tear the demo down"
echo ""
echo "  Start here: ./control-panel.sh -> http://localhost:7100"
echo "  (runs in the foreground outside Docker, on purpose - Ctrl+C stops it;"
echo "   it links every status page, dashboard and break/fix script above)"
echo ""
