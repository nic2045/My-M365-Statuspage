#!/usr/bin/env python3
"""Synthetic Prometheus exporter for the DocuWare-cluster demo.

Not a real integration - there is no actual DocuWare/MSSQL/VMware/F5
behind this. It serves plausible, gently varying metrics under
`/metrics` so the "DocuWare - Cluster-Status (App-Owner)" Grafana
dashboard has real, live time series to plot instead of static text.
Service names (Content Server, Platform Service, Autoindex Service) are
DocuWare's actual on-premises component names (see README, DocuWare
System Architecture white paper) - the metrics themselves are fake, the
naming isn't.

Baseline scenario: a mid-size DocuWare install for ~1,000,000 customers.
An invoice run just went out, so customer-portal traffic (invoice
retrieval) is elevated and bursty rather than flat - CPU/RAM sit in a
busy-but-healthy 50-75% band with visible movement, no alarms, unless
break-docuware.sh flips STATE_FILE to "unhealthy".

State toggle: reads STATE_FILE (default /tmp/docuware-state) on every
request. Missing or containing "healthy" -> normal values. Containing
"unhealthy" -> MSSQL node2 goes down, app/DB server 2 CPU/RAM follow it
down, WAF blocked requests and response times spike - so break-docuware.sh
/ fix-docuware.sh can flip the whole dashboard live without restarting
this process. This simulates an INFRASTRUCTURE incident, independent of
the separately-seeded "login broken" major incident (see
seed_oneuptime.py) which only affects the internal DocuWare backend used
by staff - the customer portal traffic modeled here keeps flowing either
way, matching that incident's actual (narrower) blast radius.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9200"))
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/docuware-state")

START = time.time()
_waf_requests_total = 0.0
_waf_blocked_total = 0.0
_portal_requests_total = 0.0
_invoices_retrieved_total = 0.0
_burst_until = 0.0  # monotonic time.time() the current traffic burst ends


def is_unhealthy():
    try:
        with open(STATE_FILE) as fh:
            return fh.read().strip() == "unhealthy"
    except FileNotFoundError:
        return False


def wave(period_s, low, high, phase=0.0):
    """Smooth value oscillating between low/high, plus a little jitter -
    reads as "real" traffic/load rather than a flat line."""
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.03, 0.03) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def maybe_burst():
    """~4% chance per scrape of a 1-3 minute traffic burst - the invoice
    run landing in customers' inboxes in waves rather than all at once."""
    global _burst_until
    now = time.time()
    if now > _burst_until and random.random() < 0.04:
        _burst_until = now + random.uniform(60, 180)
    return now < _burst_until


def render_metrics():
    global _waf_requests_total, _waf_blocked_total
    global _portal_requests_total, _invoices_retrieved_total
    unhealthy = is_unhealthy()
    bursting = maybe_burst()

    # ── WAF / website ────────────────────────────────────────────────────
    _waf_requests_total += random.uniform(15, 45) * (2.2 if bursting else 1)
    _waf_blocked_total += random.uniform(2.0, 6.0) if unhealthy else random.uniform(0.0, 0.5)
    website_connections = wave(45, 60, 140, phase=0.3) * (1.6 if bursting else 1)

    # ── Kundenportal / Rechnungsabruf (1.000.000 Kunden, laufender
    # Rechnungslauf) - bleibt unabhängig vom Backend-Login-Incident aktiv. ──
    portal_rate = random.uniform(8, 20) * (3.0 if bursting else 1) * (0.3 if unhealthy else 1)
    _portal_requests_total += portal_rate
    _invoices_retrieved_total += portal_rate * random.uniform(0.4, 0.7)
    portal_sessions = wave(50, 80, 260, phase=0.6) * (1.8 if bursting else 1)

    # ── DocuWare-Anwendungsdienste (echte Komponentennamen) - RAM-Nutzung
    # gegen manuell gesetztes Limit. ─────────────────────────────────────
    services = {
        "content-server": (2200, 3400, 4096, 0.0),
        "platform-service": (1400, 2200, 3072, 1.1),
        "autoindex-service": (600, 1100, 2048, 2.2),
    }

    # ── App-Server (2x, Windows) ─────────────────────────────────────────
    app1_cpu = wave(70, 50, 75, phase=0.0)
    app1_mem = wave(85, 50, 75, phase=0.4)
    app2_cpu = 0.0 if unhealthy else wave(70, 50, 75, phase=1.7)
    app2_mem = 0.0 if unhealthy else wave(85, 50, 75, phase=2.1)

    # ── DB-Cluster (2x MSSQL) ─────────────────────────────────────────────
    node2_up = 0 if unhealthy else 1
    db1_cpu = wave(75, 50, 75, phase=0.9)
    db1_mem = wave(95, 50, 75, phase=1.3)
    db2_cpu = 0.0 if unhealthy else wave(75, 50, 75, phase=2.6)
    db2_mem = 0.0 if unhealthy else wave(95, 50, 75, phase=3.0)
    replication_lag = wave(30, 0.0, 1.5) if not unhealthy else wave(15, 30, 90)
    apm_query_ms = wave(60, 15, 55) if not unhealthy else wave(20, 200, 600)
    response_ms = wave(50, 90, 160) if not unhealthy else wave(20, 400, 900)
    active_requests = wave(40, 5, 35) * (1.5 if bursting else 1)

    # ── BIG-IP F5 Loadbalancer ────────────────────────────────────────────
    lb_cpu = wave(80, 30, 55, phase=0.5) * (1.3 if bursting else 1)
    lb_throughput = wave(60, 80, 240, phase=1.0) * (1.8 if bursting else 1)
    lb_connections = website_connections * random.uniform(0.9, 1.1)

    hw = 1  # hardware stays healthy even during the app-level incident

    lines = [
        "# HELP docuware_website_active_connections Active connections to docuware.pyur.com.",
        "# TYPE docuware_website_active_connections gauge",
        f"docuware_website_active_connections {website_connections:.0f}",

        "# HELP docuware_waf_requests_total Total requests seen by the WAF in front of DocuWare.",
        "# TYPE docuware_waf_requests_total counter",
        f"docuware_waf_requests_total {_waf_requests_total:.0f}",
        "# HELP docuware_waf_blocked_total Requests blocked by the WAF.",
        "# TYPE docuware_waf_blocked_total counter",
        f"docuware_waf_blocked_total {_waf_blocked_total:.0f}",

        "# HELP docuware_customer_portal_requests_total Requests from the customer-facing invoice-retrieval portal (~1,000,000 Kunden).",
        "# TYPE docuware_customer_portal_requests_total counter",
        f"docuware_customer_portal_requests_total {_portal_requests_total:.0f}",
        "# HELP docuware_customer_portal_invoices_retrieved_total Invoices retrieved since a bulk invoice run went out.",
        "# TYPE docuware_customer_portal_invoices_retrieved_total counter",
        f"docuware_customer_portal_invoices_retrieved_total {_invoices_retrieved_total:.0f}",
        "# HELP docuware_customer_portal_active_sessions Customers currently browsing/retrieving invoices.",
        "# TYPE docuware_customer_portal_active_sessions gauge",
        f"docuware_customer_portal_active_sessions {portal_sessions:.0f}",

        "# HELP docuware_service_memory_used_mb RAM used by this DocuWare application service.",
        "# TYPE docuware_service_memory_used_mb gauge",
        "# HELP docuware_service_memory_limit_mb Manually configured alert threshold for this service's RAM use.",
        "# TYPE docuware_service_memory_limit_mb gauge",
    ]
    for name, (low, high, limit, phase) in services.items():
        used = wave(65, low, high, phase=phase)
        lines.append(f'docuware_service_memory_used_mb{{service="{name}"}} {used:.0f}')
        lines.append(f'docuware_service_memory_limit_mb{{service="{name}"}} {limit}')

    lines += [
        "# HELP docuware_appserver_cpu_percent CPU utilization of a DocuWare application server (Windows).",
        "# TYPE docuware_appserver_cpu_percent gauge",
        f'docuware_appserver_cpu_percent{{server="app1"}} {app1_cpu:.1f}',
        f'docuware_appserver_cpu_percent{{server="app2"}} {app2_cpu:.1f}',
        "# HELP docuware_appserver_memory_percent Memory utilization of a DocuWare application server.",
        "# TYPE docuware_appserver_memory_percent gauge",
        f'docuware_appserver_memory_percent{{server="app1"}} {app1_mem:.1f}',
        f'docuware_appserver_memory_percent{{server="app2"}} {app2_mem:.1f}',

        "# HELP docuware_iis_active_requests Requests currently being processed by the DocuWare web tier.",
        "# TYPE docuware_iis_active_requests gauge",
        f"docuware_iis_active_requests {active_requests:.0f}",
        "# HELP docuware_iis_response_time_ms DocuWare web tier application response time.",
        "# TYPE docuware_iis_response_time_ms gauge",
        f"docuware_iis_response_time_ms {response_ms:.1f}",

        "# HELP docuware_mssql_cluster_node_up Whether this MSSQL cluster node is up (1) or down (0).",
        "# TYPE docuware_mssql_cluster_node_up gauge",
        'docuware_mssql_cluster_node_up{node="db1"} 1',
        f'docuware_mssql_cluster_node_up{{node="db2"}} {node2_up}',
        "# HELP docuware_dbserver_cpu_percent CPU utilization of a DocuWare MSSQL cluster node (Windows).",
        "# TYPE docuware_dbserver_cpu_percent gauge",
        f'docuware_dbserver_cpu_percent{{server="db1"}} {db1_cpu:.1f}',
        f'docuware_dbserver_cpu_percent{{server="db2"}} {db2_cpu:.1f}',
        "# HELP docuware_dbserver_memory_percent Memory utilization of a DocuWare MSSQL cluster node.",
        "# TYPE docuware_dbserver_memory_percent gauge",
        f'docuware_dbserver_memory_percent{{server="db1"}} {db1_mem:.1f}',
        f'docuware_dbserver_memory_percent{{server="db2"}} {db2_mem:.1f}',
        "# HELP docuware_mssql_replication_lag_seconds Replication lag between cluster nodes.",
        "# TYPE docuware_mssql_replication_lag_seconds gauge",
        f"docuware_mssql_replication_lag_seconds {replication_lag:.2f}",
        "# HELP docuware_mssql_apm_query_duration_ms Application Performance Monitoring: average query duration.",
        "# TYPE docuware_mssql_apm_query_duration_ms gauge",
        f"docuware_mssql_apm_query_duration_ms {apm_query_ms:.1f}",

        "# HELP docuware_loadbalancer_cpu_percent CPU utilization of the BIG-IP F5 load balancer in front of the app servers.",
        "# TYPE docuware_loadbalancer_cpu_percent gauge",
        f"docuware_loadbalancer_cpu_percent {lb_cpu:.1f}",
        "# HELP docuware_loadbalancer_throughput_mbps Load balancer throughput.",
        "# TYPE docuware_loadbalancer_throughput_mbps gauge",
        f"docuware_loadbalancer_throughput_mbps {lb_throughput:.1f}",
        "# HELP docuware_loadbalancer_active_connections Active connections on the load balancer.",
        "# TYPE docuware_loadbalancer_active_connections gauge",
        f"docuware_loadbalancer_active_connections {lb_connections:.0f}",

        "# HELP docuware_vmware_host_cpu_percent CPU utilization of the VMware host running the DocuWare VMs.",
        "# TYPE docuware_vmware_host_cpu_percent gauge",
        f"docuware_vmware_host_cpu_percent {wave(70, 50, 75, phase=1.9):.1f}",
        "# HELP docuware_vmware_host_memory_percent Memory utilization of the VMware host.",
        "# TYPE docuware_vmware_host_memory_percent gauge",
        f"docuware_vmware_host_memory_percent {wave(90, 50, 75, phase=2.4):.1f}",

        "# HELP docuware_hardware_status Underlying hardware component status (1=ok, 0=degraded).",
        "# TYPE docuware_hardware_status gauge",
        f'docuware_hardware_status{{component="san"}} {hw}',
        f'docuware_hardware_status{{component="power"}} {hw}',
        f'docuware_hardware_status{{component="cooling"}} {hw}',
    ]
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
        pass  # keep container logs quiet - this is scraped every 15s


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
