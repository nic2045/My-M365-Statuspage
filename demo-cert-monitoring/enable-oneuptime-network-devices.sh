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

echo "==> Starting the 3 simulated SNMP devices (switch-a, switch-b, router-v3) ..."
docker compose -f network-simulator/docker-compose.yml up -d --build

echo "==> Registering them as OneUptime Network Devices + monitors ..."
python3 scripts/register_network_devices.py

cat <<'EOF'

==> Done. OneUptime -> Monitoring -> Network Devices lists all 3 simulated
    devices. Give the assigned probe 2 polls (default interval 5 min)
    before checking interface bandwidth/utilization charts - rates are
    computed from the counter delta between two polls.

    Topology page (once both switches have been polled): switch-a <-> switch-b
    show as LLDP-adjacent, plus two unmanaged neighbours hanging off switch-a
    (an unregistered "core-router" and a Cisco IP phone via CDP) that offer
    "Add to Monitoring" once clicked.

    Full walkthrough (discovery scans, traps, connected-endpoint discovery):
    https://github.com/OneUptime/oneuptime/blob/master/Examples/snmp-simulator/README.md
EOF
