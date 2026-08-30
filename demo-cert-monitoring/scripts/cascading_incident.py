#!/usr/bin/env python3
"""Live break/fix for the cascading Leipzig-internet-outage demo scenario.

Same standalone pattern as security_incident.py / blueant_incident.py, but
unlike every other live scenario in this demo (exactly one monitor, one
cause) this one deliberately touches three: the Internet-Anbindung at
Standort Leipzig fails first (root cause), and because the WLAN
controller and parts of the internal LAN tooling are cloud-managed, WLAN
and Netzwerk (LAN) degrade shortly after as a *consequence* - not three
independent incidents. `break` stages this in two visible phases (root
cause, then ~15s later the downstream impact) instead of setting all
three unhealthy at once, so a live demo actually shows the cascade
happening rather than just a before/after snapshot. One Incident, three
monitors attached - "impact grouping" (one notification, one root cause
called out) instead of three separate alerts.

Uses three Leipzig monitors no other live scenario in this demo touches
(Internet-Anbindung, Netzwerk (LAN), WLAN - only ever used by the static
scheduled-maintenance seed data before this), so it can't collide with
anything else.

Usage: python3 cascading_incident.py break|fix
Invoked by ../break-leipzig-cascade.sh / ../fix-leipzig-cascade.sh, which
set OU_BASE.
"""
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

ROOT_CAUSE_MONITOR = "Internet-Anbindung"
DOWNSTREAM_MONITORS = ["Netzwerk (LAN)", "WLAN"]
INCIDENT_TITLE = "Internetausfall mit Kettenreaktion (Standort Leipzig)"
CASCADE_DELAY_SECONDS = int(os.environ.get("CASCADE_DELAY_SECONDS", "15"))

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

all_monitor_names = [ROOT_CAUSE_MONITOR] + DOWNSTREAM_MONITORS
monitor_ids = {}
for name in all_monitor_names:
    m = find_by_name("monitor", name)
    if not m:
        sys.exit(f"ERROR: monitor '{name}' not found - run ./seed-oneuptime.sh first.")
    monitor_ids[name] = m["_id"]

statuses = get_list("monitor-status", select={
    "_id": True, "isOperationalState": True, "isOfflineState": True, "isDegradedState": True})
operational_status_id = next(s["_id"] for s in statuses if s.get("isOperationalState"))
offline_status_id = next(
    (s["_id"] for s in statuses if s.get("isOfflineState")), operational_status_id)
degraded_status_id = next(
    (s["_id"] for s in statuses if s.get("isDegradedState")), operational_status_id)


def set_monitor_status(monitor_name, status_id):
    call(f"/api/monitor/{monitor_ids[monitor_name]}", {"data": {
        "currentMonitorStatusId": status_id,
    }}, method="PUT")


mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "break":
    severities = get_list("incident-severity")
    severity_id = next((s["_id"] for s in severities if "Major" in s.get("name", "")),
                        next((s["_id"] for s in severities if "Minor" in s.get("name", "")),
                             severities[0]["_id"]))
    incident_states = get_list("incident-state", select={
        "_id": True, "name": True, "isAcknowledgedState": True, "isResolvedState": True})
    identified_state_id = next(
        (s["_id"] for s in incident_states if s.get("name") == "Identified"),
        next((s["_id"] for s in incident_states
              if not s.get("isAcknowledgedState") and not s.get("isResolvedState")),
             incident_states[0]["_id"]))

    root_cause_description = (
        "Die Internet-Anbindung am Standort Leipzig ist vollständig "
        "ausgefallen. **Root Cause: Internet-Anbindung.** Auswirkungen "
        "auf weitere Dienste werden aktuell geprüft."
    )
    # Same forward-only-state-transition constraint as the other live
    # scenarios (see security_incident.py) - a resolved incident can't be
    # reopened via PUT, only recreated.
    existing = find_by_name("incident", INCIDENT_TITLE, name_field="title",
                            select={"_id": True, "title": True, "currentIncidentState": {"isResolvedState": True}})
    if existing and (existing.get("currentIncidentState") or {}).get("isResolvedState"):
        call(f"/api/incident/{existing['_id']}", None, method="DELETE")
        existing = None

    print(f"==> Phase 1: '{ROOT_CAUSE_MONITOR}' fällt aus (Root Cause).")
    set_monitor_status(ROOT_CAUSE_MONITOR, offline_status_id)

    if existing:
        incident_id = existing["_id"]
        call(f"/api/incident/{incident_id}", {"data": {
            "title": INCIDENT_TITLE, "description": root_cause_description,
            "incidentSeverityId": severity_id,
            "monitors": [entity_ref(monitor_ids[ROOT_CAUSE_MONITOR])],
        }}, method="PUT")
    else:
        created = call("/api/incident", {"data": {
            "title": INCIDENT_TITLE, "description": root_cause_description,
            "incidentSeverityId": severity_id,
            "currentIncidentStateId": identified_state_id,
            "monitors": [entity_ref(monitor_ids[ROOT_CAUSE_MONITOR])],
            "projectId": project_id,
        }})
        incident_id = created.get("data", {}).get("_id") or created.get("_id")

    print(f"    Incident '{INCIDENT_TITLE}' ist aktiv (Status: Identified).")
    print(f"    Kettenreaktion läuft an - warte {CASCADE_DELAY_SECONDS}s ...")
    time.sleep(CASCADE_DELAY_SECONDS)

    cascade_description = (
        "Die Internet-Anbindung am Standort Leipzig ist vollständig "
        "ausgefallen. **Root Cause: Internet-Anbindung.** Da der "
        "WLAN-Controller und Teile der internen Netzwerk-Dienste "
        "cloud-verwaltet sind, sind inzwischen zusätzlich **WLAN** und "
        "**Netzwerk (LAN)** beeinträchtigt - eine Kettenreaktion aus "
        "einer einzigen Ursache, keine drei unabhängigen Störungen. "
        "Sobald die Internet-Anbindung wiederhergestellt ist, erholen "
        "sich die Folgeschäden automatisch."
    )
    for name in DOWNSTREAM_MONITORS:
        set_monitor_status(name, degraded_status_id)
    call(f"/api/incident/{incident_id}", {"data": {
        "description": cascade_description,
        "monitors": [entity_ref(monitor_ids[n]) for n in all_monitor_names],
    }}, method="PUT")

    print(f"==> Phase 2: {', '.join(DOWNSTREAM_MONITORS)} jetzt ebenfalls betroffen (Folgeschäden).")
    print(f"    '{INCIDENT_TITLE}' verknüpft jetzt alle 3 Monitore (1 Root Cause + 2 Folgeschäden).")

elif mode == "fix":
    incident = find_by_name("incident", INCIDENT_TITLE, name_field="title")
    if not incident:
        sys.exit(f"ERROR: incident '{INCIDENT_TITLE}' not found - run './cascading_incident.py break' first.")
    incident_id = incident["_id"]

    resolution_note = (
        "**Update:** Die Internet-Anbindung am Standort Leipzig ist "
        "wiederhergestellt. WLAN und Netzwerk (LAN) haben sich als "
        "Folge automatisch erholt - alle drei Dienste sind wieder "
        "Operational."
    )
    existing_notes = get_list("incident-public-note", query={"incidentId": incident_id},
                              select={"_id": True, "note": True})
    if not any(n.get("note") == resolution_note for n in existing_notes):
        call("/api/incident-public-note", {"data": {
            "projectId": project_id,
            "incidentId": incident_id,
            "note": resolution_note,
            "shouldStatusPageSubscribersBeNotifiedOnNoteCreated": True,
        }})

    incident_states = get_list("incident-state", select={"_id": True, "isResolvedState": True})
    resolved_state_id = next(s["_id"] for s in incident_states if s.get("isResolvedState"))
    call(f"/api/incident/{incident_id}", {"data": {
        "currentIncidentStateId": resolved_state_id,
    }}, method="PUT")

    for name in all_monitor_names:
        set_monitor_status(name, operational_status_id)

    print(f"==> '{INCIDENT_TITLE}' ist jetzt Resolved.")
    print(f"    {', '.join(all_monitor_names)} wieder auf Operational gesetzt.")

else:
    sys.exit("Usage: cascading_incident.py break|fix")
