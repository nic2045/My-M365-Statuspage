#!/usr/bin/env python3
"""Synthetic Prometheus exporter for the webshop.

Not a real integration - no actual shop backend behind this. Same
"healthy with visible movement, one STATE_FILE toggles a live incident"
pattern as customer-care-metrics-exporter.py / leipzig-network-exporter.py
(as opposed to the blackbox-probed real-fixture pattern used for the
Website/DocuWare demo sites) - simplest way to give a cross-functional
audience (Marketing, Website-Betrieb, Middleware, Infra) a shared,
believable-looking overview without standing up a real shop.

Four metric groups, one per audience in the accompanying dashboard
(webshop-overview.json):
  - shop_visitors_*, shop_sessions_*, shop_orders_*, shop_revenue_*,
    shop_cart_abandonment_rate_percent, shop_conversion_rate_percent,
    shop_avg_order_value_eur, shop_traffic_by_channel,
    shop_bounce_rate_percent (Marketing)
  - shop_availability_ratio, shop_lcp_seconds, shop_inp_milliseconds,
    shop_cls_score, shop_page_load_seconds, shop_http_error_rate_percent,
    shop_search_success_rate_percent (Website-Betrieb: Performance &
    Verfügbarkeit, incl. the three Core Web Vitals)
  - shop_checkout_api_latency_ms, shop_payment_gateway_*,
    shop_inventory_api_latency_ms, shop_inventory_sync_lag_seconds,
    shop_order_queue_depth, shop_integration_error_rate_percent
    (Middleware)
  - shop_service_up, shop_service_cpu_percent, shop_service_memory_percent,
    shop_request_rate_per_second, shop_db_connections_active/_max,
    shop_cdn_cache_hit_rate_percent, shop_cdn_bandwidth_mbps (Infra)

STATE_FILE (default /tmp/webshop-state) toggles a live incident when set
to "unhealthy": checkout API latency/error rate spike, payment gateway
degrades, conversion collapses - a believable "checkout is broken"
story that reads across all four groups at once (Marketing sees
conversion drop, Website-Betrieb sees error rate rise, Middleware sees
the checkout/payment latency, Infra sees the checkout service's CPU
spike) - no live break-/fix-*.sh wired up yet, but the exporter is
ready for one.
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


def is_unhealthy():
    try:
        with open(STATE_FILE) as fh:
            return fh.read().strip() == "unhealthy"
    except FileNotFoundError:
        return False


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
    unhealthy = is_unhealthy()
    lines = []

    def emit(name, help_text, metric_type, series):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        lines.extend(series)

    # ── Marketing ──────────────────────────────────────────────────────
    visitors = wave(180, 40, 30 if unhealthy else 220, phase=0.0)
    emit("shop_visitors_active", "Concurrent visitors on the webshop right now.", "gauge",
         [f"shop_visitors_active {visitors:.0f}"])

    session_rate = wave(180, 0.3, 0.2 if unhealthy else 2.6, phase=0.3)
    emit("shop_sessions_total", "Sessions started (monotonic counter).", "counter",
         [f"shop_sessions_total {counter(session_rate):.0f}"])

    order_rate = session_rate * (0.008 if unhealthy else wave(300, 0.02, 0.045, phase=0.5))
    emit("shop_orders_total", "Completed orders (monotonic counter).", "counter",
         [f"shop_orders_total {counter(order_rate):.0f}"])

    avg_order_value = wave(400, 42, 68, phase=0.7)
    emit("shop_revenue_eur_total", "Order revenue in EUR (monotonic counter).", "counter",
         [f"shop_revenue_eur_total {counter(order_rate) * avg_order_value:.2f}"])

    emit("shop_avg_order_value_eur", "Average order value in EUR.", "gauge",
         [f"shop_avg_order_value_eur {avg_order_value:.2f}"])

    conversion = (0.4 if unhealthy else wave(300, 2.1, 3.6, phase=0.4))
    emit("shop_conversion_rate_percent", "Orders / sessions, percent.", "gauge",
         [f"shop_conversion_rate_percent {conversion:.2f}"])

    cart_abandonment = (91 if unhealthy else wave(300, 62, 71, phase=0.2))
    emit("shop_cart_abandonment_rate_percent", "Carts created but never converted, percent.", "gauge",
         [f"shop_cart_abandonment_rate_percent {cart_abandonment:.1f}"])

    bounce_rate = wave(240, 35, 48, phase=0.6)
    emit("shop_bounce_rate_percent", "Sessions with a single pageview, percent.", "gauge",
         [f"shop_bounce_rate_percent {bounce_rate:.1f}"])

    channel_lines = []
    for i, ch in enumerate(CHANNELS):
        share = CHANNEL_SHARE[ch] + wave(200, -1.5, 1.5, phase=i)
        channel_lines.append(f'shop_traffic_by_channel{{channel="{ch}"}} {share:.1f}')
    emit("shop_traffic_by_channel", "Share of sessions by acquisition channel, percent.", "gauge",
         channel_lines)

    # ── Website-Betrieb: Performance & Verfügbarkeit ────────────────────
    availability = (0.87 if unhealthy else wave(600, 0.995, 0.9995, phase=0.1))
    emit("shop_availability_ratio", "Rolling webshop availability (0-1).", "gauge",
         [f"shop_availability_ratio {availability:.4f}"])

    lcp = (4.8 if unhealthy else wave(220, 1.4, 2.3, phase=0.3))
    emit("shop_lcp_seconds", "Largest Contentful Paint, seconds (Core Web Vital).", "gauge",
         [f"shop_lcp_seconds {lcp:.2f}"])

    inp = (680 if unhealthy else wave(220, 90, 190, phase=0.5))
    emit("shop_inp_milliseconds", "Interaction to Next Paint, milliseconds (Core Web Vital).", "gauge",
         [f"shop_inp_milliseconds {inp:.0f}"])

    cls = wave(300, 0.02, 0.09, phase=0.7)
    emit("shop_cls_score", "Cumulative Layout Shift score (Core Web Vital).", "gauge",
         [f"shop_cls_score {cls:.3f}"])

    page_load_lines = []
    for i, page in enumerate(PAGES):
        base = PAGE_BASE_LOAD_S[page]
        load = base * (2.6 if unhealthy and page == "Checkout" else 1) + wave(150, 0, 0.3, phase=i)
        page_load_lines.append(f'shop_page_load_seconds{{page="{page}"}} {load:.2f}')
    emit("shop_page_load_seconds", "Page load time by page type, seconds.", "gauge", page_load_lines)

    error_lines = []
    for code_class, base_low, base_high in [("4xx", 0.3, 1.1), ("5xx", 0.02, 0.3)]:
        rate = (9.5 if unhealthy and code_class == "5xx" else wave(180, base_low, base_high, phase=hash(code_class) % 10))
        error_lines.append(f'shop_http_error_rate_percent{{code_class="{code_class}"}} {rate:.2f}')
    emit("shop_http_error_rate_percent", "HTTP error rate by status class, percent.", "gauge", error_lines)

    search_success = wave(260, 92, 98, phase=0.9)
    emit("shop_search_success_rate_percent", "Site search queries returning at least one result, percent.", "gauge",
         [f"shop_search_success_rate_percent {search_success:.1f}"])

    # ── Middleware ───────────────────────────────────────────────────
    checkout_latency = (1450 if unhealthy else wave(200, 90, 220, phase=0.2))
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

    # ── Infra ────────────────────────────────────────────────────────
    up_lines = []
    cpu_lines = []
    mem_lines = []
    for i, svc in enumerate(SERVICES):
        degraded = unhealthy and svc == "checkout"
        up = 0 if degraded else 1
        cpu = wave(90, 78, 96, phase=i) if degraded else wave(90, 20, 55, phase=i)
        mem = wave(120, 70, 88, phase=i + 1) if degraded else wave(120, 30, 60, phase=i + 1)
        up_lines.append(f'shop_service_up{{service="{svc}"}} {up}')
        cpu_lines.append(f'shop_service_cpu_percent{{service="{svc}"}} {cpu:.1f}')
        mem_lines.append(f'shop_service_memory_percent{{service="{svc}"}} {mem:.1f}')
    emit("shop_service_up", "Webshop microservice reachable (1=up).", "gauge", up_lines)
    emit("shop_service_cpu_percent", "Webshop microservice CPU utilization.", "gauge", cpu_lines)
    emit("shop_service_memory_percent", "Webshop microservice memory utilization.", "gauge", mem_lines)

    request_rate = (session_rate * 14) * (0.4 if unhealthy else 1)
    emit("shop_request_rate_per_second", "HTTP requests per second across the webshop.", "gauge",
         [f"shop_request_rate_per_second {request_rate:.1f}"])

    db_active = (185 if unhealthy else wave(150, 20, 70, phase=0.5))
    emit("shop_db_connections_active", "Active database connections.", "gauge",
         [f"shop_db_connections_active {db_active:.0f}"])
    emit("shop_db_connections_max", "Configured maximum database connections.", "gauge",
         ["shop_db_connections_max 200"])

    cdn_hit_rate = wave(300, 88, 96, phase=0.2)
    emit("shop_cdn_cache_hit_rate_percent", "CDN cache hit rate, percent.", "gauge",
         [f"shop_cdn_cache_hit_rate_percent {cdn_hit_rate:.1f}"])

    cdn_bandwidth = wave(240, 45, 180, phase=0.4) * (0.5 if unhealthy else 1)
    emit("shop_cdn_bandwidth_mbps", "CDN egress bandwidth, Mbps.", "gauge",
         [f"shop_cdn_bandwidth_mbps {cdn_bandwidth:.1f}"])

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
