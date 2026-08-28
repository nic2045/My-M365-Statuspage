#!/bin/sh
# Prepares a ready-to-show OneUptime setup for this demo: a demo account,
# a project, one "Incoming Request" (heartbeat) monitor per demo target,
# and a public status page carrying all of them - then writes the
# generated heartbeat URLs back into .env so oneuptime-sync actually has
# something to sync.
#
# Without this, a fresh OneUptime is empty and the OneUptime half of the
# walkthrough (README "Vorfall in OneUptime sichtbar machen") can't be
# shown at all.
#
# Idempotent: re-running reuses the existing account, project, monitors
# and status page instead of creating duplicates.
#
# Requires the OneUptime stack to be up:
#   ./start-demo.sh --with-oneuptime
#
# Usage:
#   ./seed-oneuptime.sh
#   ./seed-oneuptime.sh --email me@example.com --password 'S3cret!'
#   ./seed-oneuptime.sh --heartbeat-minutes 2
set -eu

cd "$(dirname "$0")"

OU_EMAIL="demo@example.com"
OU_PASSWORD="DemoDemo123!"
OU_PROJECT="Zertifikats-Monitoring Demo"
HEARTBEAT_MINUTES="5"

usage() {
  awk 'NR>1 { if (/^#/) { sub(/^# ?/, ""); print } else { exit } }' "$0"
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --email)              OU_EMAIL="${2:?--email needs a value}"; shift 2 ;;
    --password)           OU_PASSWORD="${2:?--password needs a value}"; shift 2 ;;
    --project)            OU_PROJECT="${2:?--project needs a value}"; shift 2 ;;
    --heartbeat-minutes)  HEARTBEAT_MINUTES="${2:?--heartbeat-minutes needs a value}"; shift 2 ;;
    -h|--help)            usage 0 ;;
    *) echo "ERROR: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR: python3 is required (only the standard library is used)." >&2
  exit 1
}

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
[ -f "$ONEUPTIME_CONFIG" ] || {
  echo "ERROR: $ONEUPTIME_CONFIG not found - OneUptime isn't set up yet." >&2
  echo "       Run: ./start-demo.sh --with-oneuptime" >&2
  exit 1
}
[ -f .env ] || {
  echo "ERROR: .env not found - run ./start-demo.sh first." >&2
  exit 1
}

OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
OU_PORT="${OU_PORT:-80}"
if [ "$OU_PORT" = "80" ]; then
  OU_BASE="http://localhost"
  OU_SYNC_BASE="http://host.docker.internal"
else
  OU_BASE="http://localhost:$OU_PORT"
  OU_SYNC_BASE="http://host.docker.internal:$OU_PORT"
fi

# OU_BASE is what a human (and this script) uses from the host.
# OU_SYNC_BASE is what goes into .env, because the heartbeat URLs are
# fetched from inside the oneuptime-sync container, where "localhost"
# is that container itself - not the host running OneUptime.

export OU_BASE OU_SYNC_BASE OU_EMAIL OU_PASSWORD OU_PROJECT HEARTBEAT_MINUTES

# The seeding logic lives in scripts/seed_oneuptime.py (plain file, not an
# embedded heredoc) - it has grown too large to comfortably edit as one.
python3 scripts/seed_oneuptime.py

STATUS_PAGE_ID=$(python3 -c 'import json;print(json.load(open(".oneuptime-demo-summary"))["statusPageId"])' 2>/dev/null || echo "")
IT_SERVICE_STATUS_PAGE_ID=$(python3 -c 'import json;print(json.load(open(".oneuptime-demo-summary"))["itServiceStatusPageId"])' 2>/dev/null || echo "")
LEIPZIG_STATUS_PAGE_ID=$(python3 -c 'import json;print(json.load(open(".oneuptime-demo-summary"))["leipzigStatusPageId"])' 2>/dev/null || echo "")

echo "==> Restarting oneuptime-sync so it picks up the new heartbeat URLs ..."
docker compose up -d --force-recreate oneuptime-sync >/dev/null 2>&1 || true

echo ""
echo "================================================================"
echo " OneUptime demo data ready."
echo "================================================================"
echo "  OneUptime ........ $OU_BASE"
echo "  Login ............ $OU_EMAIL / $OU_PASSWORD"
if [ -n "$STATUS_PAGE_ID" ]; then
  echo "  Zertifikate ...... $OU_BASE/status-page/$STATUS_PAGE_ID"
fi
if [ -n "$IT_SERVICE_STATUS_PAGE_ID" ]; then
  echo "  IT-Services ...... $OU_BASE/status-page/$IT_SERVICE_STATUS_PAGE_ID"
fi
if [ -n "$LEIPZIG_STATUS_PAGE_ID" ]; then
  echo "  Standort Leipzig . $OU_BASE/status-page/$LEIPZIG_STATUS_PAGE_ID"
fi
echo ""
echo "  oneuptime-sync now pings these monitors every SYNC_INTERVAL_SECONDS."
echo "  Run ./break-demo.sh to watch the fixture go down on the status page."
echo ""
