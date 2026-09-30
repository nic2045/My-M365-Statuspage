#!/bin/sh
# Reverses break-container-platform.sh: flips the container-platform
# exporter's checkout-2 pod back to healthy (Ready, no more restarts,
# deployment back to 3/3), live, and resolves the matching OneUptime
# incident (if OneUptime is set up).
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the container-platform exporter's checkout-2 pod back to 'healthy' ..."
docker compose exec -T container-platform-metrics-exporter sh -c 'rm -f /tmp/container-platform-state'

echo ""
echo "==> Done. The pod recovers within ~15-30s (restart counter stays as history, stops climbing)."

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
if [ -f "$ONEUPTIME_CONFIG" ]; then
  OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
  OU_PORT="${OU_PORT:-80}"
  if [ "$OU_PORT" = "80" ]; then
    OU_BASE="http://localhost"
  else
    OU_BASE="http://localhost:$OU_PORT"
  fi
  export OU_BASE
  echo ""
  echo "==> Resolving the matching OneUptime incident ..."
  python3 scripts/container_platform_incident.py fix
fi
