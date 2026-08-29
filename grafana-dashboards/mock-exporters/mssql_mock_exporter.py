#!/usr/bin/env python3
"""Synthetic Prometheus exporter mimicking sql_exporter's common
"mssql_standard" collector metric shape - NOT a real SQL Server connection.

Exists purely to make the "MS SQL Server" dashboard show non-empty sample
data out of the box (see ../README.md). Metric names follow the commonly
used mssql_* convention for this class of exporter, but were not verified
against the exact panel queries of the fetched community dashboard (that
dashboard couldn't be downloaded from this sandbox - see fetch script) -
if a panel still shows "No data" once you have the real dashboard JSON,
check its query against the metric names below and adjust either side.

To point real data at the same dashboard instead: run the real
sql_exporter (burningalchemist/sql_exporter) with a mssql_standard
collector config against your actual SQL Server, and drop this container.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9399"))
START = time.time()

INSTANCE = "sql-prod-01"
DATABASES = ["ERP_Prod", "CRM_Prod"]


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.02, 0.02) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def render_metrics():
    lines = [
        "# HELP mssql_up Whether the last scrape of SQL Server succeeded (1=up).",
        "# TYPE mssql_up gauge",
        f'mssql_up{{instance="{INSTANCE}"}} 1',
        "",
        "# HELP mssql_connections Current number of user connections.",
        "# TYPE mssql_connections gauge",
        f'mssql_connections{{instance="{INSTANCE}"}} {wave(240, 40, 180):.0f}',
        "",
        "# HELP mssql_batch_requests_per_sec Batch requests per second.",
        "# TYPE mssql_batch_requests_per_sec gauge",
        f'mssql_batch_requests_per_sec{{instance="{INSTANCE}"}} {wave(180, 50, 900):.1f}',
        "",
        "# HELP mssql_buffer_cache_hit_ratio Buffer cache hit ratio percent - best practice target >95.",
        "# TYPE mssql_buffer_cache_hit_ratio gauge",
        f'mssql_buffer_cache_hit_ratio{{instance="{INSTANCE}"}} {wave(600, 96.5, 99.8):.2f}',
        "",
        "# HELP mssql_page_life_expectancy_seconds Page life expectancy - best practice target >300s.",
        "# TYPE mssql_page_life_expectancy_seconds gauge",
        f'mssql_page_life_expectancy_seconds{{instance="{INSTANCE}"}} {wave(900, 800, 3600):.0f}',
        "",
        "# HELP mssql_deadlocks_per_sec Deadlocks per second.",
        "# TYPE mssql_deadlocks_per_sec gauge",
        f'mssql_deadlocks_per_sec{{instance="{INSTANCE}"}} {max(0, wave(300, -0.05, 0.15)):.3f}',
        "",
        "# HELP mssql_user_errors_per_sec User errors per second.",
        "# TYPE mssql_user_errors_per_sec gauge",
        f'mssql_user_errors_per_sec{{instance="{INSTANCE}"}} {max(0, wave(200, -0.5, 1.5)):.2f}',
        "",
        "# HELP mssql_log_growths Cumulative transaction log auto-growth events.",
        "# TYPE mssql_log_growths counter",
        f'mssql_log_growths{{instance="{INSTANCE}"}} {3 + int((time.time() - START) // 3600)}',
        "",
        "# HELP mssql_full_scans_per_sec Full table/index scans per second - watch for unexpected spikes.",
        "# TYPE mssql_full_scans_per_sec gauge",
        f'mssql_full_scans_per_sec{{instance="{INSTANCE}"}} {wave(150, 1, 12):.2f}',
    ]

    db_size_lines = [
        "",
        "# HELP mssql_database_size_bytes Current database file size.",
        "# TYPE mssql_database_size_bytes gauge",
    ]
    conn_lines = [
        "",
        "# HELP mssql_database_connections Current connections per database.",
        "# TYPE mssql_database_connections gauge",
    ]
    for i, db in enumerate(DATABASES):
        base_size = (40 + i * 25) * 1024**3  # ~40-65 GiB baseline
        growth = (time.time() - START) * 1500  # slow, steady growth over the run
        db_size_lines.append(
            f'mssql_database_size_bytes{{instance="{INSTANCE}",database="{db}"}} {base_size + growth:.0f}'
        )
        conn_lines.append(
            f'mssql_database_connections{{instance="{INSTANCE}",database="{db}"}} '
            f"{wave(200, 5, 60, phase=i):.0f}"
        )

    return "\n".join(lines + db_size_lines + conn_lines) + "\n"


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
