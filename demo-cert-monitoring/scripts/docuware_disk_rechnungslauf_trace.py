#!/usr/bin/env python3
"""Root-cause trace+logs for the DocuWare "Festplatte läuft voll" scenario
(break-docuware-disk.sh / fix-docuware-disk.sh).

docuware_disk_incident.py already creates the OneUptime incident and flips
the Grafana disk-usage metric - both show *that* the Dokumentenspeicher
volume is full, not *why*. This script sends one Tempo trace + matching
Loki log lines showing a batch-chunk of the new invoice run ("Rechnungslauf
RL-2026-09") writing far more documents than the usual nightly volume -
the actual root cause an app owner would find by drilling from the disk
alert into Explore. `fix` sends a small, regular nightly batch for
contrast, matching the "healthy" variant convention of the other trace
scripts in this demo (docuware_apm_tempo_trace.py /
docuware_apm_loki_logs.py).

Same conventions as those scripts: plain stdlib urllib, no SDK, unauthenticated
Tempo OTLP/HTTP POST, trace/span ids hex-encoded (OTLP/HTTP JSON requires hex,
not base64 - see docuware_apm_tempo_trace.py's random_hex_id() note). Tempo
and Loki sends are independent and best-effort (one failing doesn't block the
other or fail the script) - this is supplementary evidence for the incident,
not the incident itself.

Usage: python3 docuware_disk_rechnungslauf_trace.py break|fix
Invoked by ../break-docuware-disk.sh / ../fix-docuware-disk.sh, which set
TEMPO_BASE (http://localhost:<TEMPO_OTLP_HTTP_PORT>, default 4318) and
LOKI_BASE (http://localhost:<LOKI_HTTP_PORT>, default 3100).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

TEMPO_BASE = os.environ.get("TEMPO_BASE", "http://localhost:4318")
LOKI_BASE = os.environ.get("LOKI_BASE", "http://localhost:3100")

INTERNAL = 1  # OTLP SpanKind: background batch pipeline, not an RPC boundary


def post_json(url, payload, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def int_attr(key, value):
    return {"key": key, "value": {"intValue": str(value)}}


def double_attr(key, value):
    return {"key": key, "value": {"doubleValue": value}}


def string_attr(key, value):
    return {"key": key, "value": {"stringValue": value}}


def build_trace_payload(healthy, trace_id_hex):
    """Four spans, all INTERNAL (no network boundary - it's one batch
    pipeline): batch-controller -> content-server (bulk store) ->
    autoindex-service (bulk index) -> SAN write. Root-cause evidence
    (document/data counts, resulting disk %) lives as span attributes on
    the root span, visible directly in the Tempo trace view - not just in
    the log lines."""
    now_ns = int(time.time() * 1e9)

    if healthy:
        run_name = "Nachtlauf-Standard"
        root_attrs = [
            string_attr("docuware.rechnungslauf.name", run_name),
            int_attr("docuware.rechnungslauf.documents_in_chunk", 180),
            int_attr("docuware.rechnungslauf.documents_total_run", 11800),
            int_attr("docuware.rechnungslauf.data_written_mb", 90),
            double_attr("docuware.rechnungslauf.disk_usage_percent_after", 64.1),
        ]
        spans_def = [
            ("docuware-rechnungslauf-batch", "run-batch-chunk (regulärer Nachtlauf)", 0, 6200, root_attrs),
            ("docuware-content-server", "store-documents (bulk, 180 Dokumente)", 100, 5400, []),
            ("docuware-autoindex-service", "index-documents (bulk, 180 Dokumente)", 300, 3100, []),
            ("docuware-storage-san", "write Dokumentenspeicher-Volume (+90 MB)", 500, 1900, []),
        ]
    else:
        run_name = "RL-2026-09"
        root_attrs = [
            string_attr("docuware.rechnungslauf.name", run_name),
            int_attr("docuware.rechnungslauf.documents_in_chunk", 2480),
            int_attr("docuware.rechnungslauf.documents_total_run", 84560),
            int_attr("docuware.rechnungslauf.documents_total_normal", 12000),
            int_attr("docuware.rechnungslauf.data_written_mb", 1300),
            double_attr("docuware.rechnungslauf.disk_usage_percent_after", 93.4),
        ]
        spans_def = [
            ("docuware-rechnungslauf-batch", "run-batch-chunk (RL-2026-09, Chunk 47/210)", 0, 38000, root_attrs),
            ("docuware-content-server", "store-documents (bulk, 2.480 Dokumente)", 200, 34200, []),
            ("docuware-autoindex-service", "index-documents (bulk, 2.480 Dokumente)", 500, 21300, []),
            ("docuware-storage-san", "write Dokumentenspeicher-Volume (+1.3 GB)", 900, 14100, []),
        ]

    trace_start_ns = now_ns - spans_def[0][3] * 1_000_000
    span_ids = [os.urandom(8).hex() for _ in spans_def]

    resource_spans_list = []
    for i, (service_name, span_name, start_offset_ms, end_offset_ms, attrs) in enumerate(spans_def):
        span = {
            "traceId": trace_id_hex,
            "spanId": span_ids[i],
            "name": span_name,
            "kind": INTERNAL,
            "startTimeUnixNano": str(trace_start_ns + start_offset_ms * 1_000_000),
            "endTimeUnixNano": str(trace_start_ns + end_offset_ms * 1_000_000),
            "status": {"code": "STATUS_CODE_OK"},
        }
        if i > 0:
            span["parentSpanId"] = span_ids[i - 1]
        if attrs:
            span["attributes"] = attrs
        resource_spans_list.append({
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": service_name}}]},
            "scopeSpans": [{"scope": {"name": "demo-disk-incident"}, "spans": [span]}],
        })

    return run_name, {"resourceSpans": resource_spans_list}


def send_trace(healthy, trace_id_hex):
    run_name, payload = build_trace_payload(healthy, trace_id_hex)
    post_json(f"{TEMPO_BASE}/v1/traces", payload)
    return run_name


def build_log_streams(healthy, trace_hex):
    now_ns = int(time.time() * 1e9)
    if healthy:
        lines = [
            ("docuware-rechnungslauf-batch",
             "Regulärer Nachtlauf gestartet: 180 Rechnungen - Volumen wieder im "
             "Normalbereich nach Bereinigung"),
            ("docuware-content-server", "store-documents: 180 Dokumente geschrieben (~90 MB), Chunk-Dauer 5.4s"),
            ("docuware-autoindex-service", "index-documents: 180 Dokumente indexiert, Warteschlange normal"),
            ("docuware-storage-san", "Dokumentenspeicher-Volume: 64.1% (stabil)"),
        ]
    else:
        lines = [
            ("docuware-rechnungslauf-batch",
             "Rechnungslauf 'RL-2026-09' Chunk 47/210 gestartet: 2.480 Rechnungen "
             "(PDF+Anhänge) - Gesamtlauf bislang 84.560 von ~210.000, deutlich über "
             "dem üblichen Volumen von ca. 12.000/Nacht"),
            ("docuware-content-server", "store-documents: 2.480 Dokumente geschrieben (~1.3 GB), Chunk-Dauer 34.2s"),
            ("docuware-autoindex-service",
             "index-documents: 2.480 Dokumente indexiert, Warteschlange kurzzeitig auf 3.400 gestiegen"),
            ("docuware-storage-san", "Dokumentenspeicher-Volume: 91.8% -> 93.4% nach diesem Batch-Chunk"),
        ]

    streams = []
    for i, (service_name, message) in enumerate(lines):
        line = f"{message} (trace_id={trace_hex})"
        streams.append({
            "stream": {"service_name": service_name},
            "values": [[str(now_ns + i * 1_000_000), line]],
        })
    return streams


def send_logs(healthy, trace_hex):
    payload = {"streams": build_log_streams(healthy, trace_hex)}
    post_json(f"{LOKI_BASE}/loki/api/v1/push", payload)


def run(healthy):
    trace_id_hex = os.urandom(16).hex()

    try:
        run_name = send_trace(healthy, trace_id_hex)
        print(f"    Trace an Tempo gesendet: Rechnungslauf-Batch '{run_name}' "
              "(docuware-rechnungslauf-batch -> content-server -> autoindex-service -> storage-san)")
        print(f"    Trace-ID: {trace_id_hex}")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"    (Tempo-Trace übersprungen - {exc})")

    try:
        send_logs(healthy, trace_id_hex)
        print("    Logs an Loki gesendet: docuware-rechnungslauf-batch/-content-server/-autoindex-service/-storage-san")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"    (Loki-Logs übersprungen - {exc})")

    print("    Ansehen: Grafana -> Explore -> Datenquelle 'Tempo' -> TraceQL "
          "'{resource.service.name=\"docuware-rechnungslauf-batch\"}', oder "
          "Datenquelle 'Loki' -> '{service_name=~\"docuware-rechnungslauf.*|"
          "docuware-content-server|docuware-autoindex-service|docuware-storage-san\"}'")


mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "break":
    run(healthy=False)
elif mode == "fix":
    run(healthy=True)
else:
    sys.exit("Usage: docuware_disk_rechnungslauf_trace.py break|fix")
