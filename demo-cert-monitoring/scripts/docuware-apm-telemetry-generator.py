#!/usr/bin/env python3
"""Continuous background telemetry for the DocuWare APM story: sends one
healthy docuware-frontend -> docuware-api-gateway -> docuware-service ->
docuware-db trace (+ matching log lines, same trace id) to Tempo and Loki
every few seconds, forever - same "busy but healthy" baseline principle as
docuware-metrics-exporter.py/customer-care-metrics-exporter.py, just pushed
telemetry instead of a scraped /metrics endpoint.

Purpose: opening Grafana Explore (Tempo/Loki) or the APM metrics dashboard
right after ./start-demo.sh should already show real, moving data instead
of an empty page - the manually-triggered incident
(break-docuware-apm.sh/fix-docuware-apm.sh) is a deliberate deviation from
this baseline, not the only data point in existence. Deliberately never
sends the slow/error variant itself - that stays exclusive to
break-docuware-apm.sh so the live-triggered incident remains a clear,
attributable event against a calm baseline instead of noise.

Runs inside the docker-compose network (TEMPO_BASE/LOKI_BASE default to the
service DNS names, unlike break-/fix-docuware-apm.sh's host-side
localhost:<port> URLs) - see the docuware-apm-telemetry-generator service
in docker-compose.yml.
"""
import base64
import json
import os
import random
import time
import urllib.error
import urllib.request

TEMPO_BASE = os.environ.get("TEMPO_BASE", "http://tempo:4318")
LOKI_BASE = os.environ.get("LOKI_BASE", "http://loki:3100")
INTERVAL_SECONDS = float(os.environ.get("INTERVAL_SECONDS", "10"))

SPAN_NAMES = [
    ("docuware-frontend", "GET /login", 3),
    ("docuware-api-gateway", "POST /api/documents/search", 2),
    ("docuware-service", "search-documents", 2),
    ("docuware-db", "SELECT * FROM documents", 2),
]
LOG_TEMPLATES = [
    ("docuware-frontend", "GET /login - 200 OK ({dur}ms)"),
    ("docuware-api-gateway", "POST /api/documents/search -> docuware-service OK ({dur}ms)"),
    ("docuware-service", "search-documents: {hits} Treffer gefunden ({dur}ms)"),
    ("docuware-db", "SELECT * FROM documents - {hits} Zeilen ({dur}ms)"),
]


def send_trace(trace_id_raw, durations_ms):
    """durations_ms holds each span's OWN duration (frontend/gateway/
    service/db, index 0..3). All four spans share one end point ("now") and
    start earlier the longer they run - since each span is a synchronous
    wait on its child, a shorter child duration nests cleanly inside its
    longer parent's window this way (child starts later, same end), with
    no timestamp-overlap bugs to get wrong."""
    trace_id = base64.b64encode(trace_id_raw).decode()
    now_ns = int(time.time() * 1e9)
    span_ids = [base64.b64encode(os.urandom(8)).decode() for _ in SPAN_NAMES]

    resource_spans = []
    for i, (service_name, span_name, kind) in enumerate(SPAN_NAMES):
        span = {
            "traceId": trace_id,
            "spanId": span_ids[i],
            "name": span_name,
            "kind": kind,
            "startTimeUnixNano": str(now_ns - durations_ms[i] * 1_000_000),
            "endTimeUnixNano": str(now_ns),
            "status": {"code": "STATUS_CODE_OK"},
        }
        if i > 0:
            span["parentSpanId"] = span_ids[i - 1]
        resource_spans.append({
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": service_name}}]},
            "scopeSpans": [{"scope": {"name": "demo-baseline"}, "spans": [span]}],
        })

    payload = {"resourceSpans": resource_spans}
    req = urllib.request.Request(
        f"{TEMPO_BASE}/v1/traces", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def send_logs(trace_id_raw, durations_ms, hits):
    trace_hex = trace_id_raw.hex()
    now_ns = int(time.time() * 1e9)
    streams = []
    for i, (service_name, template) in enumerate(LOG_TEMPLATES):
        line = template.format(dur=durations_ms[i], hits=hits) + f" (trace_id={trace_hex})"
        streams.append({
            "stream": {"service_name": service_name},
            "values": [[str(now_ns + i * 1_000_000), line]],
        })
    payload = {"streams": streams}
    req = urllib.request.Request(
        f"{LOKI_BASE}/loki/api/v1/push", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def emit_once():
    trace_id_raw = os.urandom(16)
    # Built innermost-out so each parent's duration is always >= its
    # child's (required for send_trace()'s shared-end-point nesting to
    # stay valid) - db is the base cost, each layer out adds its own
    # overhead on top. Re-rolled every tick instead of one fixed shape, so
    # it doesn't look like a static screenshot.
    db_ms = random.randint(8, 25)
    service_ms = db_ms + random.randint(5, 15)
    gateway_ms = service_ms + random.randint(3, 10)
    frontend_ms = gateway_ms + random.randint(2, 8)
    durations_ms = [frontend_ms, gateway_ms, service_ms, db_ms]
    hits = random.randint(8, 40)
    try:
        send_trace(trace_id_raw, durations_ms)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"(tempo push skipped: {exc})", flush=True)
    try:
        send_logs(trace_id_raw, durations_ms, hits)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"(loki push skipped: {exc})", flush=True)


if __name__ == "__main__":
    while True:
        emit_once()
        time.sleep(INTERVAL_SECONDS * random.uniform(0.7, 1.3))
