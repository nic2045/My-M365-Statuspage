#!/usr/bin/env python3
"""Live break/fix for the printer-maintenance-process demo scenario (#148).

Standalone (unlike seed_oneuptime.py, which runs its whole seed flow at
import time and isn't safe to import as a library) - this only touches
one Scheduled Maintenance entry it owns, on the already-seeded printer
monitor and Leipzig status page, so ./seed-oneuptime.sh must have run at
least once before this works.

Story this demonstrates (issue #148): "Drucker meldet Störung" - a fault
gets reported - "Techniker stellt Wartung ein" - IT reacts by scheduling
a maintenance window on short notice - "Mitarbeiter bekommt durch
Statuspage Info" - the Leipzig status page shows it immediately.
Crucially, the printer monitor itself is never touched here: it stays
Operational throughout, exactly what "Drucker ist bis zur Wartung nicht
eingeschränkt" (not restricted until the maintenance) means - Scheduled
Maintenance only announces upcoming impact, it does not itself set an
outage. This complements (not replaces) the static "next Friday"
printer-maintenance entry seed_oneuptime.py always creates - same
pattern as the live security-incident scenario sitting alongside three
already-resolved historical incidents (see security_incident.py):
a distinct, separately named entry so the live-triggered story never
collides with or overwrites the routine one.

Usage: python3 printer_maintenance.py break|fix
Invoked by ../break-printer.sh / ../fix-printer.sh, which set OU_BASE.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ["OU_BASE"]
EMAIL = os.environ.get("OU_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("OU_PASSWORD", "DemoDemo123!")
PROJECT_NAME = os.environ.get("OU_PROJECT", "Zertifikats-Monitoring Demo")

PRINTER_MONITOR_NAME = "Drucker (Hauptgebäude)"
LEIPZIG_PAGE_NAME = "Statusseite Standort Leipzig"
MAINTENANCE_TITLE = "Kurzfristige Wartung – Drucker (Hauptgebäude)"

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


def entity_ref(obj_id):
    return {"_id": obj_id}


def iso(dt):
    # Same conversion as seed_oneuptime.py's iso(): ScheduledMaintenance's
    # Date/DateTime columns take a plain ISO string, and every `dt` built
    # here is a naive local-time value that must go through the local
    # tzinfo before formatting as UTC - see seed_oneuptime.py for the bug
    # this avoids (dates landing hours in the future otherwise).
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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

printer_monitor = find_by_name("monitor", PRINTER_MONITOR_NAME)
if not printer_monitor:
    sys.exit(f"ERROR: monitor '{PRINTER_MONITOR_NAME}' not found - run ./seed-oneuptime.sh first.")
printer_monitor_id = printer_monitor["_id"]

leipzig_page = find_by_name("status-page", LEIPZIG_PAGE_NAME)
if not leipzig_page:
    sys.exit(f"ERROR: status page '{LEIPZIG_PAGE_NAME}' not found - run ./seed-oneuptime.sh first.")
leipzig_page_id = leipzig_page["_id"]

sm_states = get_list("scheduled-maintenance-state", select={
    "_id": True, "name": True, "isScheduledState": True, "isResolvedState": True})
scheduled_state_id = next(s["_id"] for s in sm_states if s.get("isScheduledState"))
resolved_state_id = next(s["_id"] for s in sm_states if s.get("isResolvedState"))

mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "break":
    now = datetime.now()
    starts_at = now + timedelta(hours=2)
    ends_at = starts_at + timedelta(hours=3)

    description = (
        "Der Drucker im Hauptgebäude hat eine Störung gemeldet. Die IT hat "
        "daraufhin kurzfristig ein Wartungsfenster eingeplant: "
        f"{starts_at.strftime('%H:%M')}–{ends_at.strftime('%H:%M')} Uhr. "
        "**Der Drucker funktioniert bis zum Beginn der Wartung ganz normal "
        "weiter** - erst während des Wartungsfensters bitte auf den "
        "Drucker im 2. OG (Raum 214) oder den Farbdrucker in der "
        "Teeküche ausweichen. Bei dringenden Druckaufträgen wendet euch "
        "an den IT-Helpdesk (Ext. 4242)."
    )

    # Same forward-only state-transition rule as incidents (see
    # security_incident.py) applies here too - a Resolved entry can't move
    # back to Scheduled via PUT, so a stale one from a previous run gets
    # deleted and recreated instead, same as that script's incident retrigger.
    existing = find_by_name(
        "scheduled-maintenance", MAINTENANCE_TITLE, name_field="title",
        select={"_id": True, "title": True,
                "currentScheduledMaintenanceState": {"isResolvedState": True}})
    if existing and (existing.get("currentScheduledMaintenanceState") or {}).get("isResolvedState"):
        call(f"/api/scheduled-maintenance/{existing['_id']}", None, method="DELETE")
        existing = None

    payload = {
        "title": MAINTENANCE_TITLE, "description": description,
        "startsAt": iso(starts_at), "endsAt": iso(ends_at),
        "monitors": [entity_ref(printer_monitor_id)],
        "statusPages": [entity_ref(leipzig_page_id)],
        "shouldStatusPageSubscribersBeNotifiedOnEventCreated": True,
    }
    if existing:
        payload["currentScheduledMaintenanceStateId"] = scheduled_state_id
        call(f"/api/scheduled-maintenance/{existing['_id']}", {"data": payload}, method="PUT")
    else:
        payload["currentScheduledMaintenanceStateId"] = scheduled_state_id
        payload["projectId"] = project_id
        call("/api/scheduled-maintenance", {"data": payload})

    print(f"==> '{MAINTENANCE_TITLE}' ist jetzt angekündigt (Status: Scheduled).")
    print(f"    Fenster: {starts_at.strftime('%d.%m. %H:%M')}–{ends_at.strftime('%H:%M')} Uhr.")
    print(f"    Monitor '{PRINTER_MONITOR_NAME}' bleibt Operational - keine Einschränkung bislang.")

elif mode == "fix":
    maintenance = find_by_name("scheduled-maintenance", MAINTENANCE_TITLE, name_field="title")
    if not maintenance:
        sys.exit(f"ERROR: '{MAINTENANCE_TITLE}' not found - run './printer_maintenance.py break' first.")

    call(f"/api/scheduled-maintenance/{maintenance['_id']}", {"data": {
        "currentScheduledMaintenanceStateId": resolved_state_id,
    }}, method="PUT")

    print(f"==> '{MAINTENANCE_TITLE}' ist jetzt abgeschlossen (Status: Completed).")

else:
    sys.exit("Usage: printer_maintenance.py break|fix")
