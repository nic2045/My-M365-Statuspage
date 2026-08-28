#!/bin/sh
# Tears the demo down again - counterpart to start-demo.sh.
#
# OneUptime is stopped by default whenever it's actually set up
# (oneuptime-selfhosted/oneuptime/config.env exists) - it runs as a
# separate compose project specifically so it doesn't bloat the main
# docker-compose.yml, but that means a plain `docker compose down` in
# this directory never touches it and leaves 7 heavy containers
# (Postgres/ClickHouse/Redis/...) running in the background. Pass
# --no-oneuptime to skip it (e.g. to keep OneUptime up across a quick
# core-stack restart) or --with-oneuptime for backwards compatibility
# (now the default, kept as an accepted no-op).
#
# By default only stops/removes the containers and keeps the volumes, so
# Prometheus/OneUptime history and the Grafana setup survive a restart.
# Use --purge to drop the volumes too (fresh start next time).
#
# Usage:
#   ./stop-demo.sh                  # stop core stack + OneUptime (if set up), keep data
#   ./stop-demo.sh --no-oneuptime   # only stop the core stack, leave OneUptime running
#   ./stop-demo.sh --purge          # also delete volumes (irreversible)
set -eu

cd "$(dirname "$0")"

STOP_ONEUPTIME=1
PURGE=0

for arg in "$@"; do
  case "$arg" in
    --with-oneuptime) STOP_ONEUPTIME=1 ;;  # now the default; accepted for compatibility
    --no-oneuptime)   STOP_ONEUPTIME=0 ;;
    --purge)          PURGE=1 ;;
    -h|--help)        awk 'NR>1 { if (/^#/) { sub(/^# ?/, ""); print } else { exit } }' "$0"; exit 0 ;;
    *) echo "ERROR: unknown option '$arg' (try --help)" >&2; exit 2 ;;
  esac
done

if [ "$PURGE" = "1" ]; then
  echo "==> Stopping core stack AND deleting its volumes ..."
  docker compose down --volumes --remove-orphans
else
  echo "==> Stopping core stack (volumes kept) ..."
  docker compose down --remove-orphans
fi

if [ "$STOP_ONEUPTIME" = "1" ]; then
  ONEUPTIME_DIR="oneuptime-selfhosted/oneuptime"
  if [ -f "$ONEUPTIME_DIR/config.env" ]; then
    if [ "$PURGE" = "1" ]; then
      echo "==> Stopping OneUptime AND deleting its volumes (Postgres/ClickHouse data) ..."
      ( cd "$ONEUPTIME_DIR" && docker compose --env-file config.env down --volumes --remove-orphans )
    else
      echo "==> Stopping OneUptime (volumes kept) ..."
      ( cd "$ONEUPTIME_DIR" && docker compose --env-file config.env down --remove-orphans )
    fi
  else
    echo "==> OneUptime not set up ($ONEUPTIME_DIR/config.env missing) - nothing to stop."
  fi
else
  echo "==> --no-oneuptime given - leaving OneUptime running (if it is)."
fi

echo ""
echo "==> Done. Bring it back with ./start-demo.sh --with-oneuptime"
