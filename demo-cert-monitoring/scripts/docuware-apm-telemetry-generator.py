#!/usr/bin/env python3
"""Continuous background telemetry for the DocuWare APM story: sends one
healthy docuware-frontend -> docuware-api-gateway -> docuware-service ->
docuware-db trace (+ matching log lines, same trace id) to Tempo, Loki AND
(best-effort, if seeded) OneUptime every few seconds, forever - same "busy
but healthy" baseline principle as
docuware-metrics-exporter.py/customer-care-metrics-exporter.py, just pushed
telemetry instead of a scraped /metrics endpoint.

Purpose: opening Grafana Explore (Tempo/Loki), the APM metrics dashboard,
or OneUptime's own Telemetry views right after ./start-demo.sh should
already show real, moving data instead of an empty page - and having the
identical baseline in both places at all times (not just right after a
manual break-docuware-apm.sh run) is what makes "compare OneUptime's basic
ingestion against the dedicated Tempo/Loki stack" a live, ongoing
demonstration instead of a one-shot snapshot. The manually-triggered
incident (break-docuware-apm.sh/fix-docuware-apm.sh) stays a deliberate
deviation from this baseline in all three - this script never sends the
slow/error variant itself.

OneUptime auth is cached for the life of the process (login + project
lookup + telemetry-ingestion-key lookup happen at most once, retried only
after a failure) - OneUptime enforces a sign-in rate limit
(IDENTITY_LOGIN_RATE_LIMIT_PER_ACCOUNT_PER_WINDOW, see README) that a
fresh login every ~10s would blow through in minutes. Only the telemetry
POSTs themselves (no auth) repeat every tick. If OneUptime isn't set up
(--with-oneuptime never run) or unreachable, this half is silently skipped
- same best-effort principle as the Tempo/Loki sends.

Runs inside the docker-compose network - TEMPO_BASE/LOKI_BASE default to
the service DNS names; OU_BASE defaults to host.docker.internal (OneUptime
runs in its own separate compose project on the host, same reason
oneuptime-sync.sh in this same stack uses that hostname) - see the
docuware-apm-telemetry-generator service in docker-compose.yml.
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
OU_BASE = os.environ.get("OU_BASE", "http://host.docker.internal")
OU_EMAIL = os.environ.get("OU_EMAIL", "demo@example.com")
OU_PASSWORD = os.environ.get("OU_PASSWORD", "DemoDemo123!")
OU_PROJECT = os.environ.get("OU_PROJECT", "Zertifikats-Monitoring Demo")
OU_TELEMETRY_KEY_NAME = "Demo Log Ingest"  # created once by seed_oneuptime.py
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


def build_resource_spans(trace_id_b64, durations_ms, token_header=None):
    """Shared span-building logic for Tempo and OneUptime - same shape,
    same trace id, just a different wire endpoint/auth. See send_trace()'s
    docstring for the nesting rationale (durations_ms decreasing index
    0..3, all spans sharing one end point)."""
    now_ns = int(time.time() * 1e9)
    span_ids = [base64.b64encode(os.urandom(8)).decode() for _ in SPAN_NAMES]
    resource_spans = []
    for i, (service_name, span_name, kind) in enumerate(SPAN_NAMES):
        span = {
            "traceId": trace_id_b64,
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
    return resource_spans


def post_json(url, payload, headers=None, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def send_trace(trace_id_raw, durations_ms):
    """durations_ms holds each span's OWN duration (frontend/gateway/
    service/db, index 0..3). All four spans share one end point ("now") and
    start earlier the longer they run - since each span is a synchronous
    wait on its child, a shorter child duration nests cleanly inside its
    longer parent's window this way (child starts later, same end), with
    no timestamp-overlap bugs to get wrong."""
    trace_id = base64.b64encode(trace_id_raw).decode()
    resource_spans = build_resource_spans(trace_id, durations_ms)
    post_json(f"{TEMPO_BASE}/v1/traces", {"resourceSpans": resource_spans})


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
    post_json(f"{LOKI_BASE}/loki/api/v1/push", {"streams": streams})


# ── OneUptime: cached auth, best-effort sends ───────────────────────────────
_ou = {"token": None, "project_id": None, "secret_key": None}


def ou_call(path, payload, token=None, project_id=None):
    req = urllib.request.Request(
        f"{OU_BASE}{path}", data=json.dumps(payload).encode() if payload is not None else None,
        method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if project_id:
        req.add_header("ProjectID", project_id)
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()
    return json.loads(body) if body else {}


def ou_authenticate():
    """Login (cached in _ou["token"] the moment it succeeds), then project +
    telemetry-ingestion-key lookup (cached once both are found). The login
    step specifically must not repeat every tick (OneUptime's sign-in rate
    limit, see module docstring) - so it only runs while _ou["token"] is
    still None, i.e. before the first successful login or after a 401
    cleared it via ou_reset_auth(). If OneUptime is reachable but not yet
    seeded (no matching project/key), the token is kept and only the two
    cheap list lookups retry on the next tick - not the login itself."""
    if _ou["token"] is None:
        login = ou_call("/api/identity/login", {"data": {
            "email": {"_type": "Email", "value": OU_EMAIL},
            "password": {"_type": "HashedString", "value": OU_PASSWORD},
        }})
        token = login.get("_miscData", {}).get("accessToken")
        if not token:
            return False
        _ou["token"] = token

    if _ou["project_id"] and _ou["secret_key"]:
        return True

    projects = ou_call("/api/project/get-list", {
        "query": {}, "select": {"_id": True, "name": True}, "sort": {}, "skip": 0, "limit": 100,
    }, token=_ou["token"]).get("data", [])
    project = next((p for p in projects if p.get("name") == OU_PROJECT), None)
    if not project:
        return False
    _ou["project_id"] = project["_id"]

    keys = ou_call("/api/telemetry-ingestion-key/get-list", {
        "query": {}, "select": {"_id": True, "name": True, "secretKey": True},
        "sort": {}, "skip": 0, "limit": 100,
    }, token=_ou["token"], project_id=_ou["project_id"]).get("data", [])
    key = next((k for k in keys if k.get("name") == OU_TELEMETRY_KEY_NAME), None)
    secret_key = (key.get("secretKey") or {}).get("value") if key else None
    if not secret_key:
        return False
    _ou["secret_key"] = secret_key
    return True


def ou_reset_auth():
    _ou["token"] = _ou["project_id"] = _ou["secret_key"] = None


def ou_emit(trace_id_raw, durations_ms, hits):
    """Best-effort: sends the same trace+logs to OneUptime, silently
    skipped if it isn't seeded/reachable. A 401 clears the cached auth so
    the next tick re-authenticates once, rather than failing forever on a
    stale token."""
    if not ou_authenticate():
        return
    trace_id = base64.b64encode(trace_id_raw).decode()
    trace_hex = trace_id_raw.hex()
    now_ns = int(time.time() * 1e9)
    headers = {"x-oneuptime-token": _ou["secret_key"]}
    try:
        resource_spans = build_resource_spans(trace_id, durations_ms)
        post_json(f"{OU_BASE}/otlp/v1/traces", {"resourceSpans": resource_spans}, headers=headers)

        resource_logs = []
        for i, (service_name, template) in enumerate(LOG_TEMPLATES):
            line = template.format(dur=durations_ms[i], hits=hits) + f" (trace_id={trace_hex})"
            resource_logs.append({
                "resource": {"attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}}]},
                "scopeLogs": [{"scope": {"name": "demo-baseline"}, "logRecords": [{
                    "timeUnixNano": str(now_ns + i * 1_000_000),
                    "severityNumber": 9,  # INFO
                    "body": {"stringValue": line},
                }]}],
            })
        post_json(f"{OU_BASE}/otlp/v1/logs", {"resourceLogs": resource_logs}, headers=headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            ou_reset_auth()
        raise


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
    try:
        ou_emit(trace_id_raw, durations_ms, hits)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"(oneuptime push skipped: {exc})", flush=True)


if __name__ == "__main__":
    while True:
        emit_once()
        time.sleep(INTERVAL_SECONDS * random.uniform(0.7, 1.3))
