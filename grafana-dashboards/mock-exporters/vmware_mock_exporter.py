#!/usr/bin/env python3
"""Synthetic Prometheus exporter mimicking pryorda/vmware_exporter's common
host/datastore metric shape - NOT a real vCenter/ESXi connection.

Exists purely to make the "VMware Host" dashboard show non-empty sample
data out of the box (see ../README.md). Metric names follow that
exporter's commonly used vmware_host_*/vmware_datastore_* convention, but
were not verified against the exact panel queries of whatever dashboard
you end up importing (grafana.com was unreachable from this sandbox, so
no specific dashboard ID could even be pinned - see README) - if a panel
shows "No data", check its query against the metric names below and
adjust either side.

To point real data at the same dashboard instead: run the real
vmware_exporter against your actual vCenter/ESXi (its own read-only
service account, configured in its own config.yml) and drop this
container.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9272"))
START = time.time()

HOSTS = ["esxi-01.example.internal", "esxi-02.example.internal"]
DATASTORES = [
    ("datastore-ssd-01", 8 * 1024**4),   # 8 TiB
    ("datastore-hdd-01", 24 * 1024**4),  # 24 TiB
]


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.02, 0.02) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def render_metrics():
    lines = [
        "# HELP vmware_host_power_state Host power state (1=poweredOn).",
        "# TYPE vmware_host_power_state gauge",
        "# HELP vmware_host_cpu_usage_average Host CPU usage percent.",
        "# TYPE vmware_host_cpu_usage_average gauge",
        "# HELP vmware_host_mem_usage_average Host memory usage percent.",
        "# TYPE vmware_host_mem_usage_average gauge",
        "# HELP vmware_host_uptime_seconds Host uptime in seconds.",
        "# TYPE vmware_host_uptime_seconds counter",
        "# HELP vmware_host_num_vm Number of VMs currently running on the host.",
        "# TYPE vmware_host_num_vm gauge",
    ]
    for i, host in enumerate(HOSTS):
        lines.append(f'vmware_host_power_state{{host="{host}"}} 1')
        lines.append(f'vmware_host_cpu_usage_average{{host="{host}"}} {wave(300, 20, 65, phase=i):.1f}')
        lines.append(f'vmware_host_mem_usage_average{{host="{host}"}} {wave(400, 45, 80, phase=i * 2):.1f}')
        lines.append(f'vmware_host_uptime_seconds{{host="{host}"}} {86400 * 47 + (time.time() - START):.0f}')
        lines.append(f'vmware_host_num_vm{{host="{host}"}} {12 + i}')

    lines += [
        "",
        "# HELP vmware_datastore_capacity_size Datastore total capacity in bytes.",
        "# TYPE vmware_datastore_capacity_size gauge",
        "# HELP vmware_datastore_freespace_size Datastore free space in bytes.",
        "# TYPE vmware_datastore_freespace_size gauge",
    ]
    for i, (ds, capacity) in enumerate(DATASTORES):
        free_frac = wave(1800, 0.25, 0.45, phase=i) / 1  # 25-45% free
        lines.append(f'vmware_datastore_capacity_size{{datastore="{ds}"}} {capacity}')
        lines.append(f'vmware_datastore_freespace_size{{datastore="{ds}"}} {capacity * free_frac:.0f}')

    return "\n".join(lines) + "\n"


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
