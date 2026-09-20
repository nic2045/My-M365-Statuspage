#!/usr/bin/env python3
"""Sends the DocuWare example request's log lines into Grafana Loki -
completes the observability trio next to Prometheus (metrics, via Tempo's
metrics-generator) and Tempo (traces): the same request chain
(docuware-frontend -> docuware-api-gateway -> docuware-service ->
docuware-db) that docuware_apm_tempo_trace.py sends as a trace also gets
one log line per service here, sharing the identical trace id embedded as
"trace_id=<hex>" in the line text - that's what makes Grafana's log<->trace
correlation work (see grafana/provisioning/datasources/loki.yml's
derivedFields and tempo.yml's tracesToLogsV2), without needing Loki's
native (and less portable) structured-metadata trace id field.

Plain stdlib urllib against Loki's push API (POST /loki/api/v1/push) - no
Promtail/Grafana Agent, same "no vendor SDK needed" approach as every other
telemetry-sending script in this demo.

Usage: python3 docuware_apm_loki_logs.py break|fix
Invoked by ../break-docuware-apm.sh / ../fix-docuware-apm.sh, which set
LOKI_BASE (http://localhost:<LOKI_HTTP_PORT>, default 3100) and
DOCUWARE_TRACE_ID_HEX (shared with docuware_apm_tempo_trace.py).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

LOKI_BASE = os.environ.get("LOKI_BASE", "http://localhost:3100")


def trace_id_hex():
    """Falls back to a fresh random id for standalone invocation, same
    convention as docuware_apm_tempo_trace.py's trace_id_bytes()."""
    override = os.environ.get("DOCUWARE_TRACE_ID_HEX")
    if override:
        return override
    return os.urandom(16).hex()


def build_streams(healthy, trace_hex):
    """One log line per service, in the same order/timing story as the
    Tempo trace: healthy=False reproduces the mockup's DB-timeout/missing-
    index narrative, healthy=True the fast/all-OK contrast."""
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

    streams = []
    for i, (service_name, message) in enumerate(lines):
        # Same nesting order as the trace (each downstream log a few ms
        # "later" than its caller) - not load-bearing for Loki itself, just
        # keeps a chronological read in Explore consistent with the trace
        # waterfall.
        ts_ns = now_ns + i * 1_000_000
        line = f"{message} (trace_id={trace_hex})"
        streams.append({
            "stream": {"service_name": service_name},
            "values": [[str(ts_ns), line]],
        })
    return streams


def send_docuware_logs(healthy):
    trace_hex = trace_id_hex()
    payload = {"streams": build_streams(healthy, trace_hex)}
    req = urllib.request.Request(
        f"{LOKI_BASE}/loki/api/v1/push", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        sys.exit(f"ERROR: Loki log push failed ({LOKI_BASE}/loki/api/v1/push) - "
                  f"HTTP {exc.code}: {body or exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"ERROR: Loki log push failed ({LOKI_BASE}/loki/api/v1/push) - {exc}")

    kind_label = "gesund" if healthy else "verlangsamt/Fehler"
    print(f"    Logs an Loki gesendet: docuware-frontend/-api-gateway/-service/-db ({kind_label})")
    print(f"    Trace-ID (in jeder Log-Zeile): {trace_hex}")
    print('    Ansehen: Grafana -> Explore -> Datenquelle \'Loki\' -> LogQL '
          '\'{service_name=~"docuware.*"}\' - Log-Zeile anklicken zeigt den '
          'verlinkten Tempo-Trace direkt an.')


mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "break":
    send_docuware_logs(healthy=False)
elif mode == "fix":
    send_docuware_logs(healthy=True)
else:
    sys.exit("Usage: docuware_apm_loki_logs.py break|fix")
