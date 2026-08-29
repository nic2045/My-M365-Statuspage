#!/usr/bin/env python3
"""Synthetic Prometheus exporter mimicking the real node_exporter's metric
shape - NOT a real host's data. Demo purposes only (see ../README.md);
replaced the earlier "run a real node_exporter" approach so the whole stack
stays self-contained fake data, consistent across all four dashboards.

Covers the metrics behind Node Exporter Full's most-used panels (CPU,
memory, disk I/O, network, filesystem, load, uptime) - NOT all ~90 panels
of that dashboard. Counter metrics (*_total) grow with real elapsed time at
a slowly-varying rate so rate()/irate() queries render sensibly, same
"wave" technique as the other exporters in this repo
(demo-cert-monitoring/scripts/*.py, mssql_mock_exporter.py).

To point real data at the same dashboard instead: run the real
node_exporter (prom/node-exporter) against a real host and drop this
container - metric names match, no dashboard changes needed.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9100"))
START = time.time()
BOOT_TIME = START - 86400 * 12  # "12 days uptime" at process start

HOSTNAME = os.environ.get("MOCK_HOSTNAME", "demo-server-01")
CPU_COUNT = 4
DISKS = ["sda"]
INTERFACES = ["eth0"]
FILESYSTEMS = [("/", "/dev/sda1", 200 * 1024**3), ("/var", "/dev/sda2", 100 * 1024**3)]

CPU_MODES = ["user", "system", "idle", "iowait", "irq", "softirq", "steal", "nice"]


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.01, 0.01) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def render_metrics():
    elapsed = time.time() - START
    lines = [
        "# HELP node_uname_info Labeled system information (value always 1).",
        "# TYPE node_uname_info gauge",
        f'node_uname_info{{sysname="Linux",release="6.8.0-demo",machine="x86_64",nodename="{HOSTNAME}"}} 1',
        "",
        "# HELP node_boot_time_seconds Unix time the system booted.",
        "# TYPE node_boot_time_seconds gauge",
        f"node_boot_time_seconds {BOOT_TIME:.0f}",
        "",
        "# HELP node_load1 1m load average.",
        "# TYPE node_load1 gauge",
        f"node_load1 {wave(120, 0.3, 2.2):.2f}",
        "# HELP node_load5 5m load average.",
        "# TYPE node_load5 gauge",
        f"node_load5 {wave(300, 0.5, 1.8):.2f}",
        "# HELP node_load15 15m load average.",
        "# TYPE node_load15 gauge",
        f"node_load15 {wave(900, 0.6, 1.5):.2f}",
    ]

    # CPU: slowly-varying per-mode fraction, converted to a cumulative
    # counter (elapsed * fraction) so irate()/rate() over it behaves.
    lines += [
        "",
        "# HELP node_cpu_seconds_total Seconds the CPU spent in each mode.",
        "# TYPE node_cpu_seconds_total counter",
    ]
    for cpu in range(CPU_COUNT):
        busy_frac = wave(280, 0.10, 0.45, phase=cpu * 0.7)
        idle_frac = 1 - busy_frac
        mode_fracs = {
            "idle": idle_frac,
            "user": busy_frac * 0.55,
            "system": busy_frac * 0.25,
            "iowait": busy_frac * 0.08,
            "irq": busy_frac * 0.02,
            "softirq": busy_frac * 0.03,
            "steal": busy_frac * 0.02,
            "nice": busy_frac * 0.05,
        }
        for mode, frac in mode_fracs.items():
            lines.append(f'node_cpu_seconds_total{{cpu="{cpu}",mode="{mode}"}} {elapsed * frac:.3f}')

    # Memory - plain gauges, no counter concerns.
    mem_total = 16 * 1024**3
    mem_available_frac = wave(400, 0.35, 0.65)
    mem_available = mem_total * mem_available_frac
    mem_cached = mem_total * wave(500, 0.10, 0.25, phase=1)
    mem_buffers = mem_total * 0.02
    mem_free = max(0, mem_available - mem_cached)
    lines += [
        "",
        "# HELP node_memory_MemTotal_bytes Total usable RAM.",
        "# TYPE node_memory_MemTotal_bytes gauge",
        f"node_memory_MemTotal_bytes {mem_total}",
        "# HELP node_memory_MemAvailable_bytes Estimated available memory for new applications.",
        "# TYPE node_memory_MemAvailable_bytes gauge",
        f"node_memory_MemAvailable_bytes {mem_available:.0f}",
        "# HELP node_memory_MemFree_bytes Free memory.",
        "# TYPE node_memory_MemFree_bytes gauge",
        f"node_memory_MemFree_bytes {mem_free:.0f}",
        "# HELP node_memory_Cached_bytes Page cache memory.",
        "# TYPE node_memory_Cached_bytes gauge",
        f"node_memory_Cached_bytes {mem_cached:.0f}",
        "# HELP node_memory_Buffers_bytes Buffer cache memory.",
        "# TYPE node_memory_Buffers_bytes gauge",
        f"node_memory_Buffers_bytes {mem_buffers:.0f}",
        "# HELP node_memory_SwapTotal_bytes Total swap space.",
        "# TYPE node_memory_SwapTotal_bytes gauge",
        f"node_memory_SwapTotal_bytes {4 * 1024**3}",
        "# HELP node_memory_SwapFree_bytes Free swap space.",
        "# TYPE node_memory_SwapFree_bytes gauge",
        f"node_memory_SwapFree_bytes {4 * 1024**3 * wave(600, 0.85, 1.0, phase=2):.0f}",
    ]

    # Disk I/O - counters.
    lines += [
        "",
        "# HELP node_disk_read_bytes_total Bytes read from disk.",
        "# TYPE node_disk_read_bytes_total counter",
        "# HELP node_disk_written_bytes_total Bytes written to disk.",
        "# TYPE node_disk_written_bytes_total counter",
        "# HELP node_disk_io_time_seconds_total Cumulative time disk spent doing I/O.",
        "# TYPE node_disk_io_time_seconds_total counter",
    ]
    for disk in DISKS:
        read_rate = 512 * 1024 * wave(200, 0.2, 1.0, phase=0.3)  # bytes/s baseline
        write_rate = 256 * 1024 * wave(220, 0.2, 1.0, phase=1.1)
        io_busy_frac = wave(240, 0.02, 0.20, phase=0.5)
        lines.append(f'node_disk_read_bytes_total{{device="{disk}"}} {elapsed * read_rate:.0f}')
        lines.append(f'node_disk_written_bytes_total{{device="{disk}"}} {elapsed * write_rate:.0f}')
        lines.append(f'node_disk_io_time_seconds_total{{device="{disk}"}} {elapsed * io_busy_frac:.3f}')

    # Network - counters.
    lines += [
        "",
        "# HELP node_network_receive_bytes_total Bytes received on the interface.",
        "# TYPE node_network_receive_bytes_total counter",
        "# HELP node_network_transmit_bytes_total Bytes transmitted on the interface.",
        "# TYPE node_network_transmit_bytes_total counter",
    ]
    for iface in INTERFACES:
        rx_rate = 2 * 1024 * 1024 * wave(150, 0.1, 1.0, phase=0.2)  # up to ~2 MB/s
        tx_rate = 1 * 1024 * 1024 * wave(170, 0.1, 1.0, phase=0.9)
        lines.append(f'node_network_receive_bytes_total{{device="{iface}"}} {elapsed * rx_rate:.0f}')
        lines.append(f'node_network_transmit_bytes_total{{device="{iface}"}} {elapsed * tx_rate:.0f}')

    # Filesystem - gauges.
    lines += [
        "",
        "# HELP node_filesystem_size_bytes Filesystem total size.",
        "# TYPE node_filesystem_size_bytes gauge",
        "# HELP node_filesystem_avail_bytes Filesystem space available to non-root users.",
        "# TYPE node_filesystem_avail_bytes gauge",
    ]
    for i, (mount, device, size) in enumerate(FILESYSTEMS):
        used_frac = wave(3600, 0.35, 0.55, phase=i)
        avail = size * (1 - used_frac)
        lines.append(f'node_filesystem_size_bytes{{device="{device}",mountpoint="{mount}",fstype="ext4"}} {size}')
        lines.append(f'node_filesystem_avail_bytes{{device="{device}",mountpoint="{mount}",fstype="ext4"}} {avail:.0f}')

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
