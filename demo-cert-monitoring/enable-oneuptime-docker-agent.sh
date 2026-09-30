#!/bin/sh
# Starts the REAL OneUptime Docker Agent (oneuptime/docker-agent:release,
# a pre-built image with a tuned OpenTelemetry Collector config -
# https://github.com/OneUptime/oneuptime/blob/master/agents/DockerAgent/README.md)
# against this machine's own Docker daemon. Unlike every *-metrics-
# exporter.py in this demo (synthetic Prometheus metrics), this is a
# genuine integration: OneUptime's native "Docker" monitoring section
# (separate from the generic Monitors list) gets real data - every
# container in this demo stack (cert-demo-*), auto-discovered, with real
# CPU/memory/network/block-I/O metrics and container logs, all over OTLP.
#
# Requires OneUptime to be seeded already (./seed-oneuptime.sh) - reuses
# the same "Demo Log Ingest" telemetry-ingestion-key every OTLP-sending
# script in this demo already uses, fetched fresh on every run and never
# written to disk (scripts/print_telemetry_key.py).
#
# Run from demo-cert-monitoring/ while the stack (and OneUptime) are up.
# Stop with: docker rm -f oneuptime-docker-agent
set -eu
cd "$(dirname "$0")"

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
if [ ! -f "$ONEUPTIME_CONFIG" ]; then
  echo "ERROR: OneUptime not set up (no $ONEUPTIME_CONFIG)." >&2
  echo "       Run ./start-demo.sh --with-oneuptime && ./seed-oneuptime.sh first." >&2
  exit 1
fi

OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
OU_PORT="${OU_PORT:-80}"
if [ "$OU_PORT" = "80" ]; then
  OU_BASE="http://localhost"
  AGENT_ONEUPTIME_URL="http://host.docker.internal"
else
  OU_BASE="http://localhost:$OU_PORT"
  AGENT_ONEUPTIME_URL="http://host.docker.internal:$OU_PORT"
fi
export OU_BASE

echo "==> Fetching the 'Demo Log Ingest' telemetry ingestion key ..."
SECRET_KEY=$(python3 scripts/print_telemetry_key.py)

echo "==> Starting oneuptime-docker-agent against this machine's Docker daemon ..."
docker rm -f oneuptime-docker-agent >/dev/null 2>&1 || true
# --add-host is the same host.docker.internal mapping oneuptime-sync
# already relies on (Docker Desktop resolves it natively; on Linux this
# is what makes it work) - the agent isn't part of docker-compose.yml's
# network, so it needs its own way to reach OneUptime's exposed port.
docker run -d \
  --name oneuptime-docker-agent \
  --user 0:0 \
  --restart unless-stopped \
  --add-host host.docker.internal:host-gateway \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /var/lib/docker/containers:/var/lib/docker/containers:ro \
  -e ONEUPTIME_URL="$AGENT_ONEUPTIME_URL" \
  -e ONEUPTIME_SERVICE_TOKEN="$SECRET_KEY" \
  -e DOCKER_HOST_NAME="demo-cert-monitoring" \
  oneuptime/docker-agent:release

echo ""
echo "==> Done. Within ~1-2 Minuten zeigt OneUptime -> Monitoring -> Docker jeden"
echo "    cert-demo-* Container (docuware-metrics-exporter, prometheus, grafana, ...)"
echo "    mit echten CPU/Memory/Netzwerk/Block-I/O-Werten und Container-Logs."
echo "    Beenden: docker rm -f oneuptime-docker-agent"
