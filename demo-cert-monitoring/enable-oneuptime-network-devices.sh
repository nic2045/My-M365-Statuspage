#!/bin/sh
# Starts 3 simulated SNMP network devices (vendored from OneUptime's own
# official example, network-simulator/) so OneUptime's native "Network
# Device" monitoring section (device pages, interface bandwidth/utilization
# charts, LLDP topology, traps) has something real to show - unlike every
# *-metrics-exporter.py in this demo (synthetic Prometheus metrics), these
# answer real SNMP over UDP/161.
#
# Registering the devices as monitors is a manual OneUptime dashboard step
# (see the printed instructions below) - OneUptime's own official example
# does the same, since Network Device monitor creation isn't part of its
# public REST API the way plain Monitors are.
#
# Requires OneUptime to be up already (./start-demo.sh --with-oneuptime).
# Run from demo-cert-monitoring/. Stop with:
#   docker compose -f network-simulator/docker-compose.yml down
set -eu
cd "$(dirname "$0")"

echo "==> Starting the 3 simulated SNMP devices (switch-a, switch-b, router-v3) ..."
docker compose -f network-simulator/docker-compose.yml up -d --build

cat <<'EOF'

==> Done. Now register the devices in OneUptime (Dashboard -> Network
    Devices -> Add), one monitor per device:

      switch-a   hostname 172.30.99.11   SNMP v2c   community "public"   port 161
      switch-b   hostname 172.30.99.12   SNMP v2c   community "public"   port 161
      router-v3  hostname 172.30.99.13   SNMP v3    user "oneuptime", authPriv,
                                          auth SHA / "authpass123", priv AES / "privpass123"

    Pick your configured probe for each, then create a "Network Device"
    monitor per device with interface monitoring enabled:
      - After the 1st poll: sysName/sysDescr + interfaces show up.
      - After the 2nd poll: bandwidth/utilization/error charts have data
        (rates are computed from the counter delta between two polls).
      - Topology page: switch-a <-> switch-b show as LLDP-adjacent, plus
        two unmanaged neighbours hanging off switch-a (an unregistered
        "core-router" and a Cisco IP phone via CDP) that offer
        "Add to Monitoring" once clicked.

    Full walkthrough (discovery scans, traps, connected-endpoint discovery):
    https://github.com/OneUptime/oneuptime/blob/master/Examples/snmp-simulator/README.md
EOF
