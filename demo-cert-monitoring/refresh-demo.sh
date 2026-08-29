#!/bin/sh
# Daily "freshness" refresh for repeated demo showings (#135):
#   1. Best-effort heals anything left broken from a previous demo (a
#      break-*.sh someone forgot to fix-*.sh) - skipped quietly for any
#      part of the stack that isn't currently running, since nothing is
#      visibly broken to an audience if it's offline.
#   2. Rotates in one freshly-resolved incident from a themed pool
#      (scripts/refresh_demo.py) and retires the oldest once more than
#      two are active, so a demo run weeks apart still has something
#      recently resolved to point at instead of the same static history.
#
# Meant to be run once a day, e.g. via cron:
#   0 6 * * * cd /path/to/demo-cert-monitoring && ./refresh-demo.sh >> /tmp/refresh-demo.log 2>&1
# Safe to run manually any time too - every step is idempotent/best-effort.
set -eu

cd "$(dirname "$0")"

echo "==> Demo refresh $(date '+%Y-%m-%d %H:%M') ..."

if ! docker compose ps --status running --services 2>/dev/null | grep -q .; then
  echo "    core stack isn't running - nothing to heal or rotate, done."
  exit 0
fi

echo "==> Healing any scenario left broken from a previous demo (best-effort) ..."
for script in fix-demo.sh fix-docuware.sh fix-customer-care.sh fix-leipzig-network.sh; do
  if [ -x "./$script" ]; then
    ./"$script" >/dev/null 2>&1 && echo "    $script: ok" || echo "    $script: nothing to fix / skipped"
  fi
done

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
if [ -f "$ONEUPTIME_CONFIG" ]; then
  for script in fix-security.sh fix-printer.sh; do
    if [ -x "./$script" ]; then
      ./"$script" >/dev/null 2>&1 && echo "    $script: ok" || echo "    $script: nothing to fix / skipped"
    fi
  done

  OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
  OU_PORT="${OU_PORT:-80}"
  if [ "$OU_PORT" = "80" ]; then
    OU_BASE="http://localhost"
  else
    OU_BASE="http://localhost:$OU_PORT"
  fi
  export OU_BASE

  echo "==> Rotating in a fresh resolved incident ..."
  python3 scripts/refresh_demo.py
else
  echo "    OneUptime not set up ($ONEUPTIME_CONFIG missing) - skipping incident rotation."
fi

echo "==> Refresh done."
