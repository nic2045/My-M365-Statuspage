#!/usr/bin/env python3
"""Synthetic Prometheus exporter mimicking the real apache_exporter
(Lusitaniae/apache_exporter) metric shape - NOT a real Apache instance.
Demo purposes only (see ../README.md); replaced the earlier "run a real
Apache2 + real apache_exporter" approach so the whole stack stays
self-contained fake data, consistent across all four dashboards.

Counter metrics (*_total) grow with real elapsed time at a slowly-varying
rate so rate()/irate() queries render sensibly, same "wave" technique as
the other exporters in this repo.

To point real data at the same dashboard instead: run a real Apache with
mod_status enabled plus the real apache_exporter against it, and drop
this container - metric names match, no dashboard changes needed.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9117"))
START = time.time()

SCOREBOARD_STATES = [
    "waiting", "starting", "reading", "sending", "keepalive",
    "dns", "closing", "logging", "finishing", "idle_cleanup", "open",
]
MAX_WORKERS = 150


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.01, 0.01) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def render_metrics():
    elapsed = time.time() - START
    req_rate = 15 * wave(120, 0.3, 1.0)  # up to ~15 req/s baseline
    avg_response_kb = 24
    busy_workers = int(wave(150, 3, 35))
    idle_workers = int(wave(180, 10, 60, phase=1))

    lines = [
        "# HELP apache_up Could the Apache server be scraped (1=up).",
        "# TYPE apache_up gauge",
        "apache_up 1",
        "",
        "# HELP apache_uptime_seconds_total Apache server uptime.",
        "# TYPE apache_uptime_seconds_total counter",
        f"apache_uptime_seconds_total {elapsed:.0f}",
        "",
        "# HELP apache_accesses_total Total accesses handled.",
        "# TYPE apache_accesses_total counter",
        f"apache_accesses_total {elapsed * req_rate:.0f}",
        "",
        "# HELP apache_sent_kilobytes_total Total kilobytes sent.",
        "# TYPE apache_sent_kilobytes_total counter",
        f"apache_sent_kilobytes_total {elapsed * req_rate * avg_response_kb:.0f}",
        "",
        "# HELP apache_cpuload Current CPU load of the Apache process(es), percent.",
        "# TYPE apache_cpuload gauge",
        f"apache_cpuload {wave(140, 2, 25):.2f}",
        "",
        "# HELP apache_workers Apache worker processes/threads by state.",
        "# TYPE apache_workers gauge",
        f'apache_workers{{state="busy"}} {busy_workers}',
        f'apache_workers{{state="idle"}} {idle_workers}',
        "",
        "# HELP apache_response_5xx_total Cumulative HTTP 5xx responses.",
        "# TYPE apache_response_5xx_total counter",
        f"apache_response_5xx_total {max(0, elapsed * wave(300, -0.001, 0.02)):.0f}",
    ]

    board_lines = [
        "",
        "# HELP apache_scoreboard Apache scoreboard slot counts by state.",
        "# TYPE apache_scoreboard gauge",
    ]
    remaining = MAX_WORKERS - busy_workers - idle_workers
    for i, state in enumerate(SCOREBOARD_STATES):
        if state == "open":
            value = max(0, remaining)
        else:
            value = max(0, int(wave(90, 0, 3, phase=i)))
        board_lines.append(f'apache_scoreboard{{state="{state}"}} {value}')

    return "\n".join(lines + board_lines) + "\n"


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
