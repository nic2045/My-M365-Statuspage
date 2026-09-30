#!/usr/bin/env python3
"""Prints the "Demo Log Ingest" telemetry-ingestion-key's secret to
stdout - the same key every OTLP-sending script in this demo already
reuses (created once by seed_oneuptime.py). Standalone like the other
scripts in this demo (no import of seed_oneuptime.py, which would re-run
its whole seed). Never writes the secret to disk - callers capture it via
command substitution (see enable-oneuptime-docker-agent.sh).

Usage: OU_BASE=http://localhost python3 print_telemetry_key.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ["OU_BASE"]
EMAIL = os.environ.get("OU_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("OU_PASSWORD", "DemoDemo123!")
PROJECT_NAME = os.environ.get("OU_PROJECT", "Zertifikats-Monitoring Demo")
TELEMETRY_KEY_NAME = os.environ.get("OU_TELEMETRY_KEY_NAME", "Demo Log Ingest")

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
    return json.loads(body) if body else {}


def typed(t, v):
    return {"_type": t, "value": v}


def find_by_name(model, name, select=None, name_field="name"):
    rows = call(f"/api/{model}/get-list", {
        "query": {}, "select": select or {"_id": True, name_field: True},
        "sort": {}, "skip": 0, "limit": 100,
    }).get("data", [])
    for row in rows:
        if row.get(name_field) == name:
            return row
    return None


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

key = find_by_name("telemetry-ingestion-key", TELEMETRY_KEY_NAME,
                    select={"_id": True, "name": True, "secretKey": True})
if not key:
    sys.exit(f"ERROR: ingestion key '{TELEMETRY_KEY_NAME}' not found - run ./seed-oneuptime.sh first.")
secret_key = (key.get("secretKey") or {}).get("value")
if not secret_key:
    sys.exit(f"ERROR: '{TELEMETRY_KEY_NAME}' has no secretKey.")

print(secret_key)
