#!/usr/bin/env python3
"""Live break/fix for the Blueant demo scenario.

Same standalone pattern as security_incident.py: only touches the one
Manual monitor and the one Incident this scenario owns, both already
created by seed_oneuptime.py, so ./seed-oneuptime.sh must have run at
least once before this works.

Story: an ad-hoc, unplanned Blueant outage - deliberately the opposite
of the only other Blueant disruption in this demo (the always-"currently
happening" Patchday maintenance in seed_oneuptime.py), which is planned
and expected. This one is a genuine, unannounced incident.

Usage: python3 blueant_incident.py break|fix
Invoked by ../break-blueant.sh / ../fix-blueant.sh, which set OU_BASE.
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

MONITOR_NAME = "Blueant"
INCIDENT_TITLE = "Blueant nicht erreichbar"

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

monitor = find_by_name("monitor", MONITOR_NAME)
if not monitor:
    sys.exit(f"ERROR: monitor '{MONITOR_NAME}' not found - run ./seed-oneuptime.sh first.")
monitor_id = monitor["_id"]

statuses = get_list("monitor-status", select={
    "_id": True, "isOperationalState": True, "isOfflineState": True})
operational_status_id = next(s["_id"] for s in statuses if s.get("isOperationalState"))
offline_status_id = next(
    (s["_id"] for s in statuses if s.get("isOfflineState")), operational_status_id)


def set_monitor_status(status_id):
    call(f"/api/monitor/{monitor_id}", {"data": {
        "currentMonitorStatusId": status_id,
    }}, method="PUT")


mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "break":
    severities = get_list("incident-severity")
    severity_id = next((s["_id"] for s in severities if "Minor" in s.get("name", "")),
                        severities[0]["_id"])
    incident_states = get_list("incident-state", select={
        "_id": True, "name": True, "isAcknowledgedState": True, "isResolvedState": True})
    identified_state_id = next(
        (s["_id"] for s in incident_states if s.get("name") == "Identified"),
        next((s["_id"] for s in incident_states
              if not s.get("isAcknowledgedState") and not s.get("isResolvedState")),
             incident_states[0]["_id"]))

    description = (
        "Blueant reagiert seit einigen Minuten nicht mehr - Anrufe und "
        "Chats über Blueant sind aktuell nicht möglich. **Betroffen ist "
        "ausschließlich Blueant**, alle anderen Dienste laufen normal. "
        "Die IT arbeitet an der Behebung."
    )
    # Same forward-only-state-transition constraint as the other live
    # scenarios (see security_incident.py) - a resolved incident can't be
    # reopened via PUT, only recreated.
    existing = find_by_name("incident", INCIDENT_TITLE, name_field="title",
                            select={"_id": True, "title": True, "currentIncidentState": {"isResolvedState": True}})
    if existing and (existing.get("currentIncidentState") or {}).get("isResolvedState"):
        call(f"/api/incident/{existing['_id']}", None, method="DELETE")
        existing = None

    if existing:
        payload = {"title": INCIDENT_TITLE, "description": description,
                  "incidentSeverityId": severity_id, "monitors": [entity_ref(monitor_id)]}
        call(f"/api/incident/{existing['_id']}", {"data": payload}, method="PUT")
    else:
        payload = {"title": INCIDENT_TITLE, "description": description,
                  "incidentSeverityId": severity_id,
                  "currentIncidentStateId": identified_state_id,
                  "monitors": [entity_ref(monitor_id)], "projectId": project_id}
        call("/api/incident", {"data": payload})

    set_monitor_status(offline_status_id)
    print(f"==> '{INCIDENT_TITLE}' ist jetzt aktiv (Status: Identified).")
    print(f"    Monitor '{MONITOR_NAME}' auf Offline gesetzt.")

elif mode == "fix":
    incident = find_by_name("incident", INCIDENT_TITLE, name_field="title")
    if not incident:
        sys.exit(f"ERROR: incident '{INCIDENT_TITLE}' not found - run './blueant_incident.py break' first.")
    incident_id = incident["_id"]

    resolution_note = (
        "**Update:** Blueant läuft wieder normal. Anrufe und Chats "
        "funktionieren uneingeschränkt."
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

    set_monitor_status(operational_status_id)
    print(f"==> '{INCIDENT_TITLE}' ist jetzt Resolved.")
    print(f"    Monitor '{MONITOR_NAME}' wieder auf Operational gesetzt.")

else:
    sys.exit("Usage: blueant_incident.py break|fix")
