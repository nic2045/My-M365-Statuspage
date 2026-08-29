#!/usr/bin/env python3
"""Synthetic Prometheus exporter for the Standort Leipzig LAN.

Not a real integration - there is no actual switch stack behind this.
Models the site's own network (distinct from the Customer-Care S2S-VPN
links into the Leipzig datacenter, which the other exporter already
covers): one core switch in the basement (Keller), one internet router,
and 10 access switches spread across 4 areas on a single floor.

Baseline: healthy with visible movement (port utilization, CPU,
temperature) so a live dashboard doesn't look frozen. STATE_FILE
(default /tmp/leipzig-network-state) toggles a real incident when set to
"unhealthy": one access switch (DEGRADED_SWITCH) drops offline - so
break-leipzig-network.sh / fix-leipzig-network.sh can demo a live
disruption without restarting this process.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9400"))
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/leipzig-network-state")

START = time.time()

CORE = "Core-Switch (Keller)"
ROUTER = "Internet-Router"

# area -> number of access switches in that area (10 total, spread
# across 4 areas on the one monitored floor)
AREAS = {
    "Verwaltung": 3,
    "Vertrieb": 3,
    "Technik": 2,
    "Besprechung": 2,
}
ACCESS_SWITCHES = [
    f"Access-Switch {area}-{i}"
    for area, count in AREAS.items()
    for i in range(1, count + 1)
]
DEGRADED_SWITCH = "Access-Switch Vertrieb-2"  # the one break-leipzig-network.sh takes down


def is_unhealthy():
    try:
        with open(STATE_FILE) as fh:
            return fh.read().strip() == "unhealthy"
    except FileNotFoundError:
        return False


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.03, 0.03) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def render_metrics():
    unhealthy = is_unhealthy()
    lines = [
        "# HELP net_device_info Static info row per network device (value always 1).",
        "# TYPE net_device_info gauge",
        f'net_device_info{{device="{ROUTER}",role="router",area="Keller"}} 1',
        f'net_device_info{{device="{CORE}",role="core",area="Keller"}} 1',
    ]
    for area, count in AREAS.items():
        for i in range(1, count + 1):
            name = f"Access-Switch {area}-{i}"
            lines.append(f'net_device_info{{device="{name}",role="access",area="{area}"}} 1')

    # role/area duplicated onto net_device_up itself (not just
    # net_device_info) so the Node-Graph "nodes" query needs only this
    # one metric - no join against net_device_info required.
    up_lines = [
        "# HELP net_device_up Device reachable via management network (1=up).",
        "# TYPE net_device_up gauge",
        f'net_device_up{{device="{ROUTER}",role="router",area="Keller"}} 1',
        f'net_device_up{{device="{CORE}",role="core",area="Keller"}} 1',
    ]
    cpu_lines = [
        "# HELP net_device_cpu_percent Device CPU utilization.",
        "# TYPE net_device_cpu_percent gauge",
        f'net_device_cpu_percent{{device="{ROUTER}"}} {wave(70, 15, 35, phase=0.1):.1f}',
        f'net_device_cpu_percent{{device="{CORE}"}} {wave(70, 20, 45, phase=0.6):.1f}',
    ]
    temp_lines = [
        "# HELP net_device_temperature_celsius Device chassis temperature.",
        "# TYPE net_device_temperature_celsius gauge",
        f'net_device_temperature_celsius{{device="{ROUTER}"}} {wave(90, 32, 40, phase=0.2):.1f}',
        f'net_device_temperature_celsius{{device="{CORE}"}} {wave(90, 34, 44, phase=0.8):.1f}',
    ]
    port_lines = [
        "# HELP net_port_utilization_percent Average port utilization across the device's active ports.",
        "# TYPE net_port_utilization_percent gauge",
    ]
    uplink_lines = [
        "# HELP net_uplink_up Uplink to the core switch is active (1=up) - access switches only.",
        "# TYPE net_uplink_up gauge",
    ]

    for area, count in AREAS.items():
        for i in range(1, count + 1):
            name = f"Access-Switch {area}-{i}"
            degraded_here = unhealthy and name == DEGRADED_SWITCH
            device_up = 0 if degraded_here else 1
            cpu = wave(20, 60, 90, phase=hash(name) % 10) if degraded_here else wave(60, 15, 40, phase=hash(name) % 10)
            temp = wave(20, 45, 60, phase=hash(name) % 10) if degraded_here else wave(90, 30, 42, phase=hash(name) % 10)
            port_util = 0 if degraded_here else wave(70, 10, 55, phase=hash(name + "p") % 10)
            uplink = 0 if degraded_here else 1

            up_lines.append(f'net_device_up{{device="{name}",role="access",area="{area}"}} {device_up}')
            cpu_lines.append(f'net_device_cpu_percent{{device="{name}"}} {cpu:.1f}')
            temp_lines.append(f'net_device_temperature_celsius{{device="{name}"}} {temp:.1f}')
            port_lines.append(f'net_port_utilization_percent{{device="{name}"}} {port_util:.1f}')
            uplink_lines.append(f'net_uplink_up{{device="{name}",area="{area}"}} {uplink}')

    all_lines = lines + up_lines + cpu_lines + temp_lines + port_lines + uplink_lines
    return "\n".join(all_lines) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = render_metrics().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
