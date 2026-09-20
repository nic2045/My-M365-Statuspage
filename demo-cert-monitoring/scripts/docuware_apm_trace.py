#!/usr/bin/env python3
"""Sends an example DocuWare request trace into OneUptime, for direct
comparison against the static gap-monitoring-today-tomorrow.html mockup
(demo-cert-monitoring/mockups/) and, later, against a dedicated APM tool
(Grafana Tempo). Same standalone login/query pattern as
cascading_incident.py / security_incident.py - no import of
seed_oneuptime.py (its top-level code would re-run the whole seed).

Reuses the "Demo Log Ingest" telemetry ingestion key seed_oneuptime.py
already created for the docuware-login logs, and OneUptime's OTLP/HTTP
trace endpoint (POST /otlp/v1/traces) - same mechanism as the cross-service
cascade trace in cascading_incident.py, just a single-service request chain
here: docuware-frontend -> docuware-api-gateway -> docuware-service ->
docuware-db, four spans sharing one traceId with parentSpanId chaining them.

`break` sends the slow/error trace matching the mockup's DocuWare story
(2.2s total, DB span ends in STATUS_CODE_ERROR - "Database Connection
Timeout", the mockup's "Index Missing" root cause in the span attributes).
`fix` sends a fast, healthy trace of the same shape for contrast - OneUptime
never had a monitor/incident tied to this, so there is no state to revert;
"fix" only adds a second, visibly different trace for comparison. Best
effort like the cascade trace: a missing telemetry key or a failed ingest
call is reported and this script exits non-zero, but must never partially
corrupt OneUptime state (it only ever POSTs new telemetry, never PUTs).

Usage: python3 docuware_apm_trace.py break|fix
Invoked by ../break-docuware-apm.sh / ../fix-docuware-apm.sh, which set
OU_BASE.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ["OU_BASE"]
EMAIL = os.environ.get("OU_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("OU_PASSWORD", "DemoDemo123!")
PROJECT_NAME = os.environ.get("OU_PROJECT", "Zertifikats-Monitoring Demo")

TELEMETRY_KEY_NAME = "Demo Log Ingest"  # created once by seed_oneuptime.py, reused here

token = None
project_id = None


def call(path, payload, method="POST"):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if project_id:
        req.add_header("ProjectID", project_id)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        sys.exit(f"ERROR: {path} -> HTTP {exc.code}: {exc.read().decode()[:300]}")
    parsed = json.loads(body) if body else {}
    if isinstance(parsed, dict) and "error" in parsed:
        sys.exit(f"ERROR: {path} -> {parsed['error']}")
    return parsed


def typed(t, v):
    return {"_type": t, "value": v}


def get_list(model, query=None, select=None, limit=100):
    return call(f"/api/{model}/get-list", {
        "query": query or {}, "select": select or {"_id": True, "name": True},
        "sort": {}, "skip": 0, "limit": limit,
    }).get("data", [])


def find_by_name(model, name, select=None, name_field="name"):
    for row in get_list(model, select=select or {"_id": True, name_field: True}):
        if row.get(name_field) == name:
            return row
    return None


def random_hex_id(num_bytes):
    """OTLP JSON encodes trace/span ids as base64 bytes on the wire, but
    OtelTracesIngestService.convertBase64ToHexSafe() decodes them straight
    back to hex - only the wire encoding is base64, ids themselves are
    plain random bytes (same note as in cascading_incident.py)."""
    return base64.b64encode(os.urandom(num_bytes)).decode()


def trace_id_bytes():
    """DOCUWARE_TRACE_ID_HEX, when set by break-/fix-docuware-apm.sh, is
    the same trace id docuware_apm_tempo_trace.py and
    docuware_apm_loki_logs.py use - one id shared across all three back
    ends. Standalone invocation without the wrapper script falls back to a
    fresh random id."""
    hex_override = os.environ.get("DOCUWARE_TRACE_ID_HEX")
    if hex_override:
        return bytes.fromhex(hex_override)
    return os.urandom(16)


def send_docuware_trace(healthy):
    """Sends one 4-span trace (docuware-frontend -> docuware-api-gateway ->
    docuware-service -> docuware-db) matching the DocuWare example in
    gap-monitoring-today-tomorrow.html. `healthy=False` reproduces the
    mockup's numbers (~2.2s, DB call errors out); `healthy=True` sends a
    fast, all-OK variant of the same shape for contrast."""
    key = find_by_name("telemetry-ingestion-key", TELEMETRY_KEY_NAME,
                        select={"_id": True, "name": True, "secretKey": True})
    if not key:
        sys.exit(f"ERROR: Ingestion-Key '{TELEMETRY_KEY_NAME}' nicht gefunden - "
                  f"./seed-oneuptime.sh muss zuerst gelaufen sein.")
    secret_key = (key.get("secretKey") or {}).get("value")
    if not secret_key:
        sys.exit(f"ERROR: '{TELEMETRY_KEY_NAME}' hat keinen secretKey.")

    trace_id_raw = trace_id_bytes()
    trace_id = base64.b64encode(trace_id_raw).decode()
    now_ns = int(time.time() * 1e9)

    if healthy:
        # Root call took 42ms total, every span ends STATUS_CODE_OK.
        spans_def = [
            ("docuware-frontend", "GET /login", 3, 0, 42, None),
            ("docuware-api-gateway", "POST /api/documents/search", 2, 2, 38, None),
            ("docuware-service", "search-documents", 2, 5, 30, None),
            ("docuware-db", "SELECT * FROM documents", 2, 8, 18, None),
        ]
    else:
        # Root call took 2.2s total - the DB span alone accounts for ~2.13s
        # of it and ends in error, matching the mockup's "2.100 ms response
        # time" / "Database Connection Timeout" / "Index Missing" story.
        spans_def = [
            ("docuware-frontend", "GET /login", 3, 0, 2200, None),
            ("docuware-api-gateway", "POST /api/documents/search", 2, 10, 2190,
             "Upstream-Aufruf docuware-service ohne Antwort im Timeout-Fenster"),
            ("docuware-service", "search-documents", 2, 30, 2180,
             "Datenbankabfrage docuware-db hat das Zeitlimit überschritten"),
            ("docuware-db", "SELECT * FROM documents", 2, 40, 2170,
             "Database Connection Timeout - Index auf documents.customer_id fehlt"),
        ]

    trace_start_ns = now_ns - int((spans_def[0][4]) * 1_000_000)
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
        if error_message:
            span["status"] = {"code": "STATUS_CODE_ERROR", "message": error_message}
        else:
            span["status"] = {"code": "STATUS_CODE_OK"}
        resource_spans_list.append({
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": service_name}}]},
            "scopeSpans": [{"scope": {"name": "demo-seed"}, "spans": [span]}],
        })

    payload = {"resourceSpans": resource_spans_list}
    req = urllib.request.Request(
        f"{BASE}/otlp/v1/traces", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-oneuptime-token", secret_key)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        sys.exit(f"ERROR: trace ingest failed - HTTP {exc.code}: {body or exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"ERROR: trace ingest failed - {exc}")

    kind_label = "gesund (42ms, alle Spans OK)" if healthy else "verlangsamt (2,2s, DB-Span mit Timeout-Fehler)"
    print(f"    Trace gesendet: docuware-frontend -> docuware-api-gateway -> "
          f"docuware-service -> docuware-db ({kind_label})")
    print(f"    Trace-ID: {trace_id_raw.hex()}")
    print("    Ansehen: OneUptime -> Traces (bzw. Traces -> Service Map für "
          "die abgeleitete Abhängigkeitskette)")


def send_docuware_logs(healthy):
    """Best-effort companion to send_docuware_trace(): the same four log
    lines docuware_apm_loki_logs.py sends to Loki, here via OneUptime's
    OTLP/HTTP logs endpoint (same 'Demo Log Ingest' key as the
    docuware-login logs from seed_oneuptime.py) - so OneUptime's Telemetry
    -> Logs gets the identical DocuWare story as Loki, for the same
    three-way comparison the Tempo trace already has. A missing key or
    failed push is reported but must not abort break/fix - the trace part
    above is the primary payload."""
    try:
        key = find_by_name("telemetry-ingestion-key", TELEMETRY_KEY_NAME,
                            select={"_id": True, "name": True, "secretKey": True})
        if not key:
            print(f"    (keine Logs gesendet - Ingestion-Key '{TELEMETRY_KEY_NAME}' nicht gefunden)")
            return
        secret_key = (key.get("secretKey") or {}).get("value")
        if not secret_key:
            print(f"    (keine Logs gesendet - '{TELEMETRY_KEY_NAME}' hat keinen secretKey)")
            return

        trace_hex = os.environ.get("DOCUWARE_TRACE_ID_HEX") or os.urandom(16).hex()
        now_ns = int(time.time() * 1e9)
        if healthy:
            lines = [
                ("docuware-frontend", "GET /login - 200 OK (42ms)"),
                ("docuware-api-gateway", "POST /api/documents/search -> docuware-service OK (38ms)"),
                ("docuware-service", "search-documents: 24 Treffer gefunden (30ms)"),
                ("docuware-db", "SELECT * FROM documents - 24 Zeilen (18ms)"),
            ]
        else:
            lines = [
                ("docuware-frontend", "GET /login - Antwort von docuware-api-gateway verzögert (2200ms)"),
                ("docuware-api-gateway", "POST /api/documents/search -> docuware-service: Timeout nach 2180ms"),
                ("docuware-service", "search-documents: Datenbankabfrage an docuware-db überschreitet Zeitlimit (2150ms)"),
                ("docuware-db", "SELECT * FROM documents: Query-Timeout nach 2130ms - Index auf documents.customer_id fehlt"),
            ]

        resource_logs = []
        for i, (service_name, message) in enumerate(lines):
            line = f"{message} (trace_id={trace_hex})"
            resource_logs.append({
                "resource": {"attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}}]},
                "scopeLogs": [{"scope": {"name": "demo-seed"}, "logRecords": [{
                    "timeUnixNano": str(now_ns + i * 1_000_000),
                    "severityNumber": 17 if not healthy else 9,  # ERROR : INFO
                    "body": {"stringValue": line},
                }]}],
            })

        log_req = urllib.request.Request(
            f"{BASE}/otlp/v1/logs", data=json.dumps({"resourceLogs": resource_logs}).encode(),
            method="POST")
        log_req.add_header("Content-Type", "application/json")
        log_req.add_header("x-oneuptime-token", secret_key)
        with urllib.request.urlopen(log_req, timeout=30) as resp:
            resp.read()
        print("    Logs gesendet: docuware-frontend/-api-gateway/-service/-db "
              f"(trace_id={trace_hex})")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"    (Log-Versand übersprungen - {exc})")


login = call("/api/identity/login", {"data": {
    "email": typed("Email", EMAIL), "password": typed("HashedString", PASSWORD),
}})
token = login.get("_miscData", {}).get("accessToken")
if not token:
    sys.exit(f"ERROR: login for {EMAIL} failed - has ./seed-oneuptime.sh run yet?")

project = find_by_name("project", PROJECT_NAME)
if not project:
    sys.exit(f"ERROR: project '{PROJECT_NAME}' not found - run ./seed-oneuptime.sh first.")
project_id = project["_id"]

mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "break":
    send_docuware_trace(healthy=False)
    send_docuware_logs(healthy=False)
elif mode == "fix":
    send_docuware_trace(healthy=True)
    send_docuware_logs(healthy=True)
else:
    sys.exit("Usage: docuware_apm_trace.py break|fix")
