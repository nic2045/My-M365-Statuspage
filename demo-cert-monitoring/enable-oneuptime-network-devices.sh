#!/bin/sh
# Starts 3 simulated SNMP network devices (vendored from OneUptime's own
# official example, network-simulator/) and registers them as OneUptime
# Network Devices + monitors via the REST API
# (scripts/register_network_devices.py) - so OneUptime's native "Network
# Device" monitoring section (device pages, interface bandwidth/utilization
# charts, LLDP topology, traps) has something real to show. Unlike every
# *-metrics-exporter.py in this demo (synthetic Prometheus metrics), these
# answer real SNMP over UDP/161.
#
# Requires OneUptime to be up already (./start-demo.sh --with-oneuptime &&
# ./seed-oneuptime.sh). Run from demo-cert-monitoring/. Stop with:
#   docker compose -f network-simulator/docker-compose.yml down
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
OU_BASE="http://localhost"
[ "$OU_PORT" != "80" ] && OU_BASE="http://localhost:$OU_PORT"
export OU_BASE

echo "==> Starting the simulated SNMP devices (switch-a, switch-b, router-v3) ..."
docker compose -f network-simulator/docker-compose.yml up -d --build

echo "==> Registering them as OneUptime Network Devices + monitors ..."
python3 scripts/register_network_devices.py

echo ""
echo "    Full walkthrough (discovery scans, traps, connected-endpoint discovery):"
echo "    https://github.com/OneUptime/oneuptime/blob/master/Examples/snmp-simulator/README.md"
