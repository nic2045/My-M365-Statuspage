#!/usr/bin/env python3
"""Registers the 3 simulated SNMP devices (network-simulator/) as OneUptime
Network Devices, and creates one "Network Device" monitor per device with
interface monitoring enabled - the step enable-oneuptime-network-devices.sh
used to print as manual Dashboard instructions.

Standalone like scripts/print_telemetry_key.py (no import of
seed_oneuptime.py, which would re-run its whole seed). Idempotent: re-running
updates the existing device/monitor by name instead of duplicating it, same
convergent pattern as seed_oneuptime.py's ensure_* helpers.

Usage: OU_BASE=http://localhost python3 register_network_devices.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ["OU_BASE"]
EMAIL = os.environ.get("OU_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("OU_PASSWORD", "DemoDemo123!")
PROJECT_NAME = os.environ.get("OU_PROJECT", "Zertifikats-Monitoring Demo")

# Matches network-simulator/docker-compose.yml and snmpd.conf exactly -
# hostnames/credentials must stay in lockstep with those files.
DEVICES = [
    {
        "name": "Netzwerk-Switch A (Simulator)",
        "hostname": "172.30.99.11",
        "snmpVersion": "V2c",
        "snmpCommunityString": "public",
    },
    {
        "name": "Netzwerk-Switch B (Simulator)",
        "hostname": "172.30.99.12",
        "snmpVersion": "V2c",
        "snmpCommunityString": "public",
    },
    {
        "name": "Netzwerk-Router V3 (Simulator)",
        "hostname": "172.30.99.13",
        "snmpVersion": "V3",
        "snmpV3SecurityLevel": "authPriv",
        "snmpV3Username": "oneuptime",
        "snmpV3AuthProtocol": "SHA",
        "snmpV3AuthKey": "authpass123",
        "snmpV3PrivProtocol": "AES",
        "snmpV3PrivKey": "privpass123",
    },
]

token = None
project_id = None


def call(path, payload, method="POST"):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if project_id:
        req.add_header("ProjectID", project_id)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        sys.exit(f"ERROR: {path} -> HTTP {exc.code}: {exc.read().decode()[:300]}")
    parsed = json.loads(body) if body else {}
    if isinstance(parsed, dict) and "error" in parsed:
        sys.exit(f"ERROR: {path} -> {parsed['error']}")
    return parsed


def typed(t, v):
    return {"_type": t, "value": v}


def get_list(model, query=None, select=None, limit=100):
    return call(f"/api/{model}/get-list", {
        "query": query or {}, "select": select or {"_id": True, "name": True},
        "sort": {}, "skip": 0, "limit": limit,
    }).get("data", [])


def find_by_name(model, name, select=None, name_field="name"):
    select = select or {"_id": True, name_field: True}
    for row in get_list(model, select=select):
        if row.get(name_field) == name:
            return row
    return None


login = call("/api/identity/login", {"data": {
    "email": typed("Email", EMAIL), "password": typed("HashedString", PASSWORD),
}})
token = login.get("_miscData", {}).get("accessToken")
if not token:
    sys.exit(f"ERROR: login for {EMAIL} failed - has ./seed-oneuptime.sh run yet?")

project = find_by_name("project", PROJECT_NAME)
if not project:
    sys.exit(f"ERROR: project '{PROJECT_NAME}' not found - run ./seed-oneuptime.sh first.")
project_id = project["_id"]

probes = get_list("probe", select={"_id": True, "name": True}, limit=1)
if not probes:
    sys.exit(
        "ERROR: no probe found - OneUptime's own probe-1/probe-2 containers "
        "register themselves within a minute of startup; wait and retry."
    )
probe_id = probes[0]["_id"]
print(f"==> Using probe '{probes[0]['name']}' ({probe_id})")

SELECT_DEVICE = {"_id": True, "name": True}
for device in DEVICES:
    payload = {k: v for k, v in device.items() if k != "name"}
    payload["probeId"] = probe_id
    payload["walkInterfaces"] = True

    existing = find_by_name("network-device", device["name"], select=SELECT_DEVICE)
    if existing:
        call(f"/api/network-device/{existing['_id']}", {"data": payload}, method="PUT")
        device_id = existing["_id"]
        print(f"    updated Network Device '{device['name']}'")
    else:
        created = call("/api/network-device", {"data": dict(payload, name=device["name"])})
        device_id = created["_id"]
        print(f"    created Network Device '{device['name']}'")

    monitor_name = f"{device['name']} - Monitor"
    monitor_steps = typed("MonitorSteps", {"monitorStepsInstanceArray": [
        typed("MonitorStep", {
            "id": "00000000-0000-4000-8000-000000000001",
            "monitorCriteria": typed("MonitorCriteria", {"monitorCriteriaInstanceArray": []}),
            "networkDeviceMonitor": {
                "networkDeviceId": device_id,
                "monitorInterfaces": True,
                "collectEndpoints": False,
                "oids": [],
            },
        }),
    ]})

    existing_monitor = find_by_name("monitor", monitor_name, select={"_id": True, "name": True})
    if existing_monitor:
        call(f"/api/monitor/{existing_monitor['_id']}",
             {"data": {"monitorSteps": monitor_steps}}, method="PUT")
        print(f"    updated Monitor '{monitor_name}'")
    else:
        call("/api/monitor", {"data": {
            "name": monitor_name,
            "description": f"SNMP-Netzwerk-Geraet ({device['hostname']}), Simulator",
            "monitorType": "Network Device",
            "monitorSteps": monitor_steps,
        }})
        print(f"    created Monitor '{monitor_name}'")

print("")
print("==> Done. OneUptime -> Monitoring -> Network Devices now lists all 3")
print("    simulated devices. Give the probe 2 polls (see its Polling")
print("    Interval, default 5 min) before checking interface bandwidth/")
print("    utilization charts and the Topology page - rates are computed")
print("    from the counter delta between two polls.")
