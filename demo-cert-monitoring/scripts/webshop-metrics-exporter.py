#!/usr/bin/env python3
"""Synthetic Prometheus exporter for shop.pyur.com.

Not a real integration - no actual shop backend behind this. Same
"healthy with visible movement, one STATE_FILE toggles a live incident"
pattern as customer-care-metrics-exporter.py / leipzig-network-exporter.py
(as opposed to the blackbox-probed real-fixture pattern used for the
Website/DocuWare demo sites) - simplest way to feed a whole GROUP of
dashboards (one exporter, one Prometheus job, five dashboards reading
different slices of the same metrics) without standing up a real shop.

The five dashboards this exporter feeds (grafana/dashboards/webshop-*.json)
mirror a real production observability stack for an e-commerce site -
Shopware-style health dashboard, frontend/RUM observability, Node-
Exporter-style infra, database performance, and web-traffic/status-code
breakdown (the Prometheus-native equivalent of a Loki+NGINX log
dashboard - no real Loki/log pipeline stood up here, see the README):

  - shop_visitors_*, shop_sessions_*, shop_orders_*, shop_revenue_*,
    shop_cart_abandonment_rate_percent, shop_conversion_rate_percent,
    shop_avg_order_value_eur, shop_traffic_by_channel,
    shop_bounce_rate_percent, shop_checkout_api_latency_ms,
    shop_payment_gateway_*, shop_inventory_*, shop_order_queue_depth,
    shop_integration_error_rate_percent
    (Health & Business - "bridges server performance and business
    bottlenecks": Marketing KPIs plus the checkout/payment/inventory
    middleware that bridges into them)
  - shop_availability_ratio, shop_lcp_seconds, shop_inp_milliseconds,
    shop_cls_score, shop_page_load_seconds, shop_search_success_rate_percent,
    shop_js_error_rate_percent, shop_js_errors_total,
    shop_funnel_step_entries_total, shop_funnel_step_avg_duration_seconds
    (Frontend Observability: Core Web Vitals, JS errors, and the
    Vertragsabschluss/Internet signup funnel - which step visitors drop
    off at and how long they dwell on each one)
  - shop_service_up, shop_service_cpu_percent, shop_service_memory_percent,
    shop_service_disk_percent, shop_service_network_mbps,
    shop_node_load1, shop_node_load5, shop_cdn_cache_hit_rate_percent,
    shop_cdn_bandwidth_mbps
    (Infrastruktur)
  - shop_db_query_latency_ms, shop_db_connections_active/_max,
    shop_db_slow_queries_total, shop_db_replication_lag_seconds,
    shop_db_deadlocks_total
    (Datenbank-Performance)
  - shop_http_requests_total (by status_class), shop_request_rate_per_second,
    shop_http_path_error_rate_percent
    (Web-Traffic & Fehlercodes)

STATE_FILE (default /tmp/webshop-state) toggles a live incident when set
to "unhealthy": ONE story that ripples through every dashboard instead
of five independent ones - the database is the root cause (query
latency and replication lag spike), which shows up as checkout API
latency/payment failures (Health & Business), as abandonment
concentrated specifically at the "Vertragsübersicht" funnel step where
the checkout API gets called plus a rise in JS errors (Frontend
Observability), as high CPU/disk on the checkout service (Infrastruktur),
as the query-latency/replication-lag spike itself (Datenbank-Performance),
and as a 5xx spike on /checkout and /vertrag/abschluss specifically
(Web-Traffic & Fehlercodes) - the same incident, traceable end-to-end
across all five dashboards.

STATE_FILE set to "ddos" is a second, deliberately different-shaped live
incident (break-ddos-shop.sh/fix-ddos-shop.sh): a DDoS against
shop.pyur.com. The tell, readable straight from the data instead of just
asserted, is the split between real-user metrics and raw traffic -
shop_visitors_active/shop_sessions_total stay on their normal healthy
wave (real people aren't flooding the site) while
shop_request_rate_per_second explodes to ~100-200x normal, status codes
swing hard into 4xx/5xx, page load/LCP/INP degrade across EVERY page
(not just Checkout like the DB incident), bounce rate spikes, and the
frontend/catalog services plus the CDN edge saturate on CPU/network/
bandwidth while cache hit rate collapses (attack traffic isn't
cacheable). Deliberately leaves the database, payment gateway,
inventory and other integrations untouched - unlike the "unhealthy"
incident above, this one is not a backend problem, and the dashboards
should make that legible at a glance.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9500"))
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/webshop-state")

START = time.time()

CHANNELS = ["organic", "paid", "direct", "referral", "social"]
CHANNEL_SHARE = {"organic": 38, "paid": 27, "direct": 18, "referral": 11, "social": 6}
PAGES = ["Startseite", "Kategorie", "Produkt", "Warenkorb", "Checkout"]
PAGE_BASE_LOAD_S = {"Startseite": 1.1, "Kategorie": 1.4, "Produkt": 1.2, "Warenkorb": 0.9, "Checkout": 1.6}
SERVICES = ["frontend", "checkout", "catalog", "search"]
INTEGRATIONS = ["payment", "inventory", "shipping", "erp"]

# Vertragsabschluss (Internet) - the funnel the user actually asked to see:
# at which step do visitors drop off, and how long do they stay on each
# one. Each entry is (step key, display label, retention fraction of the
# PREVIOUS step's entry rate, baseline dwell time in seconds). The
# "Persönliche Daten" step is deliberately the biggest drop (commitment
# point - address, name, IBAN) and the longest dwell (a form, not a click)
# - the realistic friction point in a real contract-signup funnel.
FUNNEL_STEPS = [
    ("tarifauswahl", "Tarifauswahl", 1.00, 35),
    ("verfuegbarkeit", "Verfügbarkeitsprüfung", 0.82, 22),
    ("persoenliche_daten", "Persönliche Daten", 0.58, 95),
    ("vertragsuebersicht", "Vertragsübersicht", 0.80, 40),
    ("bestaetigung", "Bestätigung", 0.90, 12),
]
HTTP_PATHS = ["/", "/tarife", "/verfuegbarkeit", "/vertrag/persoenliche-daten",
              "/vertrag/uebersicht", "/checkout", "/vertrag/abschluss"]


def get_state():
    try:
        with open(STATE_FILE) as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return "healthy"


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.01, 0.01) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def counter(rate_per_s):
    """Monotonic counter value: elapsed seconds * rate, so
    rate()/increase() queries in Grafana work like against a real
    Prometheus counter."""
    return (time.time() - START) * rate_per_s


def render_metrics():
    state = get_state()
    unhealthy = state == "unhealthy"
    ddos = state == "ddos"
    lines = []

    def emit(name, help_text, metric_type, series):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        lines.extend(series)

    # ── Health & Business: Marketing ────────────────────────────────────
    visitors = wave(180, 40, 30 if unhealthy else 220, phase=0.0)
    emit("shop_visitors_active", "Concurrent visitors on shop.pyur.com right now.", "gauge",
         [f"shop_visitors_active {visitors:.0f}"])

    session_rate = wave(180, 0.3, 0.2 if unhealthy else 2.6, phase=0.3)
    emit("shop_sessions_total", "Sessions started (monotonic counter).", "counter",
         [f"shop_sessions_total {counter(session_rate):.0f}"])

    order_rate = session_rate * (0.008 if unhealthy else wave(300, 0.02, 0.045, phase=0.5))
    emit("shop_orders_total", "Completed orders/contracts (monotonic counter).", "counter",
         [f"shop_orders_total {counter(order_rate):.0f}"])

    avg_order_value = wave(400, 42, 68, phase=0.7)
    emit("shop_revenue_eur_total", "Order revenue in EUR (monotonic counter).", "counter",
         [f"shop_revenue_eur_total {counter(order_rate) * avg_order_value:.2f}"])

    emit("shop_avg_order_value_eur", "Average order value in EUR.", "gauge",
         [f"shop_avg_order_value_eur {avg_order_value:.2f}"])

    conversion = (0.4 if unhealthy else 0.3 if ddos else wave(300, 2.1, 3.6, phase=0.4))
    emit("shop_conversion_rate_percent", "Orders / sessions, percent.", "gauge",
         [f"shop_conversion_rate_percent {conversion:.2f}"])

    cart_abandonment = (91 if unhealthy else 95 if ddos else wave(300, 62, 71, phase=0.2))
    emit("shop_cart_abandonment_rate_percent", "Carts created but never converted, percent.", "gauge",
         [f"shop_cart_abandonment_rate_percent {cart_abandonment:.1f}"])

    bounce_rate = (82 if ddos else wave(240, 35, 48, phase=0.6))
    emit("shop_bounce_rate_percent", "Sessions with a single pageview, percent.", "gauge",
         [f"shop_bounce_rate_percent {bounce_rate:.1f}"])

    channel_lines = []
    for i, ch in enumerate(CHANNELS):
        share = CHANNEL_SHARE[ch] + wave(200, -1.5, 1.5, phase=i)
        channel_lines.append(f'shop_traffic_by_channel{{channel="{ch}"}} {share:.1f}')
    emit("shop_traffic_by_channel", "Share of sessions by acquisition channel, percent.", "gauge",
         channel_lines)

    # ── Health & Business: Middleware (the "bridge" to backend performance) ──
    checkout_latency = (1450 if unhealthy else 1100 if ddos else wave(200, 90, 220, phase=0.2))
    emit("shop_checkout_api_latency_ms", "Checkout API p95 latency, milliseconds.", "gauge",
         [f"shop_checkout_api_latency_ms {checkout_latency:.0f}"])

    payment_success = (73 if unhealthy else wave(240, 98.2, 99.8, phase=0.4))
    emit("shop_payment_gateway_success_rate_percent", "Payment gateway calls succeeding, percent.", "gauge",
         [f"shop_payment_gateway_success_rate_percent {payment_success:.2f}"])

    payment_latency = (2200 if unhealthy else wave(200, 150, 400, phase=0.6))
    emit("shop_payment_gateway_latency_ms", "Payment gateway p95 latency, milliseconds.", "gauge",
         [f"shop_payment_gateway_latency_ms {payment_latency:.0f}"])

    inventory_latency = wave(220, 40, 120, phase=0.8)
    emit("shop_inventory_api_latency_ms", "Inventory API p95 latency, milliseconds.", "gauge",
         [f"shop_inventory_api_latency_ms {inventory_latency:.0f}"])

    inventory_lag = wave(300, 5, 45, phase=0.1)
    emit("shop_inventory_sync_lag_seconds", "Delay between a stock change and it showing in the catalog, seconds.", "gauge",
         [f"shop_inventory_sync_lag_seconds {inventory_lag:.0f}"])

    queue_depth = (340 if unhealthy else wave(180, 0, 25, phase=0.3))
    emit("shop_order_queue_depth", "Orders waiting for downstream (ERP/shipping) processing.", "gauge",
         [f"shop_order_queue_depth {queue_depth:.0f}"])

    integration_lines = []
    for i, integ in enumerate(INTEGRATIONS):
        rate = (18 if unhealthy and integ == "payment" else wave(200, 0.1, 1.8, phase=i * 1.3))
        integration_lines.append(f'shop_integration_error_rate_percent{{integration="{integ}"}} {rate:.2f}')
    emit("shop_integration_error_rate_percent", "Error rate by downstream integration, percent.", "gauge",
         integration_lines)

    # ── Frontend Observability: Core Web Vitals & errors ───────────────
    availability = (0.87 if unhealthy else 0.91 if ddos else wave(600, 0.995, 0.9995, phase=0.1))
    emit("shop_availability_ratio", "Rolling webshop availability (0-1).", "gauge",
         [f"shop_availability_ratio {availability:.4f}"])

    lcp = (4.8 if unhealthy else 7.5 if ddos else wave(220, 1.4, 2.3, phase=0.3))
    emit("shop_lcp_seconds", "Largest Contentful Paint, seconds (Core Web Vital).", "gauge",
         [f"shop_lcp_seconds {lcp:.2f}"])

    inp = (680 if unhealthy else 1400 if ddos else wave(220, 90, 190, phase=0.5))
    emit("shop_inp_milliseconds", "Interaction to Next Paint, milliseconds (Core Web Vital).", "gauge",
         [f"shop_inp_milliseconds {inp:.0f}"])

    cls = wave(300, 0.02, 0.09, phase=0.7)
    emit("shop_cls_score", "Cumulative Layout Shift score (Core Web Vital).", "gauge",
         [f"shop_cls_score {cls:.3f}"])

    page_load_lines = []
    for i, page in enumerate(PAGES):
        base = PAGE_BASE_LOAD_S[page]
        # Unhealthy (DB root cause) hits Checkout specifically - the DDoS
        # flood instead degrades EVERY page, which is the visible tell
        # that this is an edge/network problem, not one slow endpoint.
        mult = 2.6 if (unhealthy and page == "Checkout") else 4.5 if ddos else 1
        load = base * mult + wave(150, 0, 0.3, phase=i)
        page_load_lines.append(f'shop_page_load_seconds{{page="{page}"}} {load:.2f}')
    emit("shop_page_load_seconds", "Page load time by page type, seconds.", "gauge", page_load_lines)

    search_success = wave(260, 92, 98, phase=0.9)
    emit("shop_search_success_rate_percent", "Site search queries returning at least one result, percent.", "gauge",
         [f"shop_search_success_rate_percent {search_success:.1f}"])

    js_error_rate = (6.8 if unhealthy else 4.2 if ddos else wave(260, 0.3, 1.4, phase=0.2))
    emit("shop_js_error_rate_percent", "Sessions with at least one uncaught JS error, percent.", "gauge",
         [f"shop_js_error_rate_percent {js_error_rate:.2f}"])

    js_error_type_lines = []
    for i, err_type in enumerate(["network", "render", "script"]):
        if unhealthy and err_type == "network":
            rate = session_rate * 0.03
        elif ddos and err_type == "network":
            rate = session_rate * 0.02
        else:
            rate = wave(200, 0.001, 0.01, phase=i)
        js_error_type_lines.append(f'shop_js_errors_total{{type="{err_type}"}} {counter(rate):.0f}')
    emit("shop_js_errors_total", "Uncaught JS errors by type (monotonic counter).", "counter",
         js_error_type_lines)

    # Vertragsabschluss-Funnel: cumulative entry rate per step (each
    # step's rate = previous step's rate * that step's retention
    # fraction), rendered as monotonic counters so Grafana can show both
    # the funnel shape (instant values) and entry-rate-over-time
    # (rate()). When unhealthy, "vertragsuebersicht" loses extra
    # visitors (checkout API is where that step calls out to) on top of
    # its normal retention.
    entry_rate = session_rate * 0.35  # share of sessions that start the funnel at all
    funnel_entries_lines = []
    funnel_duration_lines = []
    step_rate = entry_rate
    for i, (key, label, retention, base_dwell) in enumerate(FUNNEL_STEPS):
        step_rate *= retention
        if unhealthy and key == "vertragsuebersicht":
            step_rate *= 0.35
        # DDoS friction isn't localized to one step like the DB incident -
        # every step loses extra visitors uniformly (broad slowness/
        # timeouts, not one broken API call).
        if ddos:
            step_rate *= 0.75
        funnel_entries_lines.append(
            f'shop_funnel_step_entries_total{{step="{key}",label="{label}"}} {counter(step_rate):.1f}')
        dwell_mult = 1.8 if (unhealthy and key == "vertragsuebersicht") else 1.4 if ddos else 1
        dwell = base_dwell * dwell_mult + wave(140, -3, 3, phase=i)
        funnel_duration_lines.append(
            f'shop_funnel_step_avg_duration_seconds{{step="{key}",label="{label}"}} {max(1, dwell):.0f}')
    emit("shop_funnel_step_entries_total",
         "Vertragsabschluss (Internet): cumulative entries per funnel step (monotonic counter).",
         "counter", funnel_entries_lines)
    emit("shop_funnel_step_avg_duration_seconds",
         "Vertragsabschluss (Internet): average time spent on each funnel step, seconds.",
         "gauge", funnel_duration_lines)

    # ── Web-Traffic & Fehlercodes ────────────────────────────────────
    # The DDoS tell: request_rate is normally derived from session_rate
    # (real sessions * requests/session) - during a flood it's decoupled
    # entirely, because the traffic driving it isn't real sessions at
    # all. That's what makes "visitors flat, requests through the roof"
    # visible across the dashboards instead of just asserted.
    if ddos:
        request_rate = wave(60, 3200, 6000, phase=0.1)
    else:
        request_rate = (session_rate * 14) * (0.4 if unhealthy else 1)
    emit("shop_request_rate_per_second", "HTTP requests per second across shop.pyur.com.", "gauge",
         [f"shop_request_rate_per_second {request_rate:.1f}"])

    status_shares = {"2xx": 96.5, "3xx": 2.2, "4xx": 1.1, "5xx": 0.2}
    if unhealthy:
        status_shares = {"2xx": 78, "3xx": 2.0, "4xx": 1.5, "5xx": 18.5}
    elif ddos:
        status_shares = {"2xx": 35, "3xx": 1.0, "4xx": 24.0, "5xx": 40.0}
    status_lines = []
    for code_class, share in status_shares.items():
        rate = request_rate * (share / 100) + wave(150, -0.2, 0.2, phase=hash(code_class) % 10)
        status_lines.append(f'shop_http_requests_total{{status_class="{code_class}"}} {counter(max(0, rate)):.0f}')
    emit("shop_http_requests_total", "HTTP requests by status class (monotonic counter).", "counter",
         status_lines)

    path_error_lines = []
    for i, path in enumerate(HTTP_PATHS):
        hot = unhealthy and path in ("/checkout", "/vertrag/abschluss")
        if hot:
            rate = 16
        elif ddos:
            # Broad, not localized - unlike the DB incident's two hot
            # paths, a flood degrades every path roughly equally.
            rate = 22 + wave(90, -2, 2, phase=i)
        else:
            rate = wave(190, 0.1, 1.6, phase=i * 0.9)
        path_error_lines.append(f'shop_http_path_error_rate_percent{{path="{path}"}} {rate:.2f}')
    emit("shop_http_path_error_rate_percent", "HTTP error rate by path, percent.", "gauge",
         path_error_lines)

    # ── Infrastruktur ────────────────────────────────────────────────
    up_lines = []
    cpu_lines = []
    mem_lines = []
    disk_lines = []
    net_lines = []
    for i, svc in enumerate(SERVICES):
        degraded = unhealthy and svc == "checkout"
        # The flood hits the edge (frontend) and the commonly-scraped
        # product listing pages (catalog) - checkout/search stay normal,
        # same "isolate where the story lives" pattern as `degraded`
        # above, just a different pair of services.
        flooded = ddos and svc in ("frontend", "catalog")
        # Still "up" - saturated and slow, not offline, matching "Shop
        # wird extrem langsam" rather than a hard outage.
        up = 0 if degraded else 1
        if degraded:
            cpu = wave(90, 78, 96, phase=i)
        elif flooded:
            cpu = wave(60, 90, 99, phase=i)
        else:
            cpu = wave(90, 20, 55, phase=i)
        mem = wave(120, 70, 88, phase=i + 1) if degraded else wave(120, 30, 60, phase=i + 1)
        disk = wave(500, 35, 60, phase=i + 2)
        net_mult = 2.4 if degraded else 8.0 if flooded else 1
        net_in = wave(100, 5, 40, phase=i) * net_mult
        net_out = wave(100, 8, 55, phase=i + 3) * net_mult
        up_lines.append(f'shop_service_up{{service="{svc}"}} {up}')
        cpu_lines.append(f'shop_service_cpu_percent{{service="{svc}"}} {cpu:.1f}')
        mem_lines.append(f'shop_service_memory_percent{{service="{svc}"}} {mem:.1f}')
        disk_lines.append(f'shop_service_disk_percent{{service="{svc}"}} {disk:.1f}')
        net_lines.append(f'shop_service_network_mbps{{service="{svc}",direction="in"}} {net_in:.1f}')
        net_lines.append(f'shop_service_network_mbps{{service="{svc}",direction="out"}} {net_out:.1f}')
    emit("shop_service_up", "Webshop microservice reachable (1=up).", "gauge", up_lines)
    emit("shop_service_cpu_percent", "Webshop microservice CPU utilization.", "gauge", cpu_lines)
    emit("shop_service_memory_percent", "Webshop microservice memory utilization.", "gauge", mem_lines)
    emit("shop_service_disk_percent", "Webshop microservice disk utilization.", "gauge", disk_lines)
    emit("shop_service_network_mbps", "Webshop microservice network throughput, Mbps.", "gauge", net_lines)

    load1 = (6.4 if unhealthy else 8.5 if ddos else wave(90, 0.8, 2.4, phase=0.2))
    load5 = (5.1 if unhealthy else 7.2 if ddos else wave(140, 1.0, 2.2, phase=0.4))
    emit("shop_node_load1", "Host load average, 1 minute.", "gauge", [f"shop_node_load1 {load1:.2f}"])
    emit("shop_node_load5", "Host load average, 5 minutes.", "gauge", [f"shop_node_load5 {load5:.2f}"])

    # Attack traffic is disproportionately non-cacheable (cache-busting
    # query strings, dynamic endpoints), so the hit rate collapses even
    # though - or rather because - egress bandwidth spikes.
    cdn_hit_rate = (28 if ddos else wave(300, 88, 96, phase=0.2))
    emit("shop_cdn_cache_hit_rate_percent", "CDN cache hit rate, percent.", "gauge",
         [f"shop_cdn_cache_hit_rate_percent {cdn_hit_rate:.1f}"])

    if ddos:
        cdn_bandwidth = wave(60, 900, 1600, phase=0.4)
    else:
        cdn_bandwidth = wave(240, 45, 180, phase=0.4) * (0.5 if unhealthy else 1)
    emit("shop_cdn_bandwidth_mbps", "CDN egress bandwidth, Mbps.", "gauge",
         [f"shop_cdn_bandwidth_mbps {cdn_bandwidth:.1f}"])

    # ── Datenbank-Performance ────────────────────────────────────────
    query_latency_lines = []
    for i, qtype in enumerate(["select", "insert", "update"]):
        base_low, base_high = (2, 12) if qtype == "select" else (5, 25)
        latency = (420 if unhealthy else wave(160, base_low, base_high, phase=i * 1.1))
        query_latency_lines.append(f'shop_db_query_latency_ms{{query_type="{qtype}"}} {latency:.1f}')
    emit("shop_db_query_latency_ms", "Database query p95 latency by type, milliseconds.", "gauge",
         query_latency_lines)

    db_active = (185 if unhealthy else wave(150, 20, 70, phase=0.5))
    emit("shop_db_connections_active", "Active database connections.", "gauge",
         [f"shop_db_connections_active {db_active:.0f}"])
    emit("shop_db_connections_max", "Configured maximum database connections.", "gauge",
         ["shop_db_connections_max 200"])

    slow_query_rate = (4.5 if unhealthy else wave(200, 0, 0.3, phase=0.3))
    emit("shop_db_slow_queries_total", "Queries exceeding the slow-query threshold (monotonic counter).", "counter",
         [f"shop_db_slow_queries_total {counter(slow_query_rate):.0f}"])

    replication_lag = (38 if unhealthy else wave(220, 0.1, 2.5, phase=0.6))
    emit("shop_db_replication_lag_seconds", "Replica lag behind primary, seconds.", "gauge",
         [f"shop_db_replication_lag_seconds {replication_lag:.2f}"])

    deadlock_rate = wave(300, 0, 0.02, phase=0.8)
    emit("shop_db_deadlocks_total", "Detected deadlocks (monotonic counter).", "counter",
         [f"shop_db_deadlocks_total {counter(deadlock_rate):.0f}"])

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
