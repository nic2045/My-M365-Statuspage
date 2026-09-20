#!/usr/bin/env python3
"""Sends the same example DocuWare request trace as docuware_apm_trace.py
(OneUptime version), but directly into Grafana Tempo - so both back ends
carry the identical story for a genuine side-by-side comparison: what does
OneUptime's own OTLP ingestion show vs. what does a dedicated APM/tracing
tool (Tempo, browsable via Grafana's Explore/Tempo datasource) show for the
exact same four-span trace.

No login/project lookup needed here (unlike OneUptime) - Tempo's OTLP/HTTP
receiver takes an unauthenticated POST in this local demo stack. Plain
stdlib urllib, no OpenTelemetry SDK, same approach as every other
trace-sending script in this demo.

Usage: python3 docuware_apm_tempo_trace.py break|fix
Invoked by ../break-docuware-apm.sh / ../fix-docuware-apm.sh, which set
TEMPO_BASE (http://localhost:<TEMPO_OTLP_HTTP_PORT>, default 4318).
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

TEMPO_BASE = os.environ.get("TEMPO_BASE", "http://localhost:4318")


def random_hex_id(num_bytes):
    """OTLP JSON encodes trace/span ids as base64 on the wire; Tempo (like
    OneUptime, see docuware_apm_trace.py) decodes them back to raw bytes -
    only the wire encoding is base64, the ids themselves are plain random
    bytes."""
    return base64.b64encode(os.urandom(num_bytes)).decode()


def build_trace_payload(healthy):
    """Same four-span shape as docuware_apm_trace.py's OneUptime version:
    docuware-frontend -> docuware-api-gateway -> docuware-service ->
    docuware-db. `healthy=False` reproduces the mockup's numbers (~2.2s,
    DB span errors out on a missing index); `healthy=True` sends a fast,
    all-OK variant of the same shape for contrast."""
    trace_id = random_hex_id(16)
    now_ns = int(time.time() * 1e9)

    if healthy:
        spans_def = [
            ("docuware-frontend", "GET /login", 3, 0, 42, None),
            ("docuware-api-gateway", "POST /api/documents/search", 2, 2, 38, None),
            ("docuware-service", "search-documents", 2, 5, 30, None),
            ("docuware-db", "SELECT * FROM documents", 2, 8, 18, None),
        ]
    else:
        spans_def = [
            ("docuware-frontend", "GET /login", 3, 0, 2200, None),
            ("docuware-api-gateway", "POST /api/documents/search", 2, 10, 2190,
             "Upstream-Aufruf docuware-service ohne Antwort im Timeout-Fenster"),
            ("docuware-service", "search-documents", 2, 30, 2180,
             "Datenbankabfrage docuware-db hat das Zeitlimit überschritten"),
            ("docuware-db", "SELECT * FROM documents", 2, 40, 2170,
             "Database Connection Timeout - Index auf documents.customer_id fehlt"),
        ]

    trace_start_ns = now_ns - int(spans_def[0][4] * 1_000_000)
    span_ids = [random_hex_id(8) for _ in spans_def]

    resource_spans_list = []
    for i, (service_name, span_name, kind, start_offset_ms, end_offset_ms, error_message) in enumerate(spans_def):
        span = {
            "traceId": trace_id,
            "spanId": span_ids[i],
            "name": span_name,
            "kind": kind,
            "startTimeUnixNano": str(trace_start_ns + start_offset_ms * 1_000_000),
            "endTimeUnixNano": str(trace_start_ns + end_offset_ms * 1_000_000),
        }
        if i > 0:
            span["parentSpanId"] = span_ids[i - 1]
        span["status"] = ({"code": "STATUS_CODE_ERROR", "message": error_message}
                           if error_message else {"code": "STATUS_CODE_OK"})
        resource_spans_list.append({
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": service_name}}]},
            "scopeSpans": [{"scope": {"name": "demo-seed"}, "spans": [span]}],
        })

    return trace_id, {"resourceSpans": resource_spans_list}


def send_docuware_trace(healthy):
    trace_id, payload = build_trace_payload(healthy)
    req = urllib.request.Request(
        f"{TEMPO_BASE}/v1/traces", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        sys.exit(f"ERROR: Tempo trace ingest failed ({TEMPO_BASE}/v1/traces) - "
                  f"HTTP {exc.code}: {body or exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"ERROR: Tempo trace ingest failed ({TEMPO_BASE}/v1/traces) - {exc}")

    kind_label = "gesund (42ms, alle Spans OK)" if healthy else "verlangsamt (2,2s, DB-Span mit Timeout-Fehler)"
    print(f"    Trace an Tempo gesendet: docuware-frontend -> docuware-api-gateway -> "
          f"docuware-service -> docuware-db ({kind_label})")
    print(f"    Trace-ID: {trace_id}")
    print("    Ansehen: Grafana -> Explore -> Datenquelle 'Tempo' -> TraceQL "
          "'{resource.service.name=\"docuware-frontend\"}', oder direkt per Trace-ID.")


mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "break":
    send_docuware_trace(healthy=False)
elif mode == "fix":
    send_docuware_trace(healthy=True)
else:
    sys.exit("Usage: docuware_apm_tempo_trace.py break|fix")
