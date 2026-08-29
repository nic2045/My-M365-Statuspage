#!/usr/bin/env python3
"""Daily "freshness" rotation for the demo (#135): adds one new resolved
incident from a themed pool and retires the oldest once the rotating set
grows past MAX_ROTATING, so a demo repeated over weeks always has a
recently-resolved incident to point at instead of the same three-week-old
security events every time.

Standalone (unlike seed_oneuptime.py, which runs its whole seed flow at
import time and isn't safe to import as a library) - this only touches
the rotating incidents it owns, all already-seeded monitors, so
./seed-oneuptime.sh must have run at least once before this works.

Which incidents belong to the rotation is tracked in a local state file
(.refresh-demo-state.json, gitignored) rather than a marker embedded in
the incident text - the whole point is these should read exactly like
any other resolved incident on the status page, not like generated
demo filler.

Usage: python3 refresh_demo.py
Invoked by ../refresh-demo.sh, which sets OU_BASE and STATE_FILE.
"""
import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ["OU_BASE"]
EMAIL = os.environ.get("OU_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("OU_PASSWORD", "DemoDemo123!")
PROJECT_NAME = os.environ.get("OU_PROJECT", "Zertifikats-Monitoring Demo")
STATE_FILE = os.environ.get(
    "REFRESH_STATE_FILE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 ".refresh-demo-state.json"))

MAX_ROTATING = 2  # how many auto-rotated incidents stay visible at once

# (title, monitor name, description) - spans several already-seeded
# IT-Services/Leipzig monitors so the rotation doesn't always land on the
# same service. Kept short and low-drama (Minor, resolved within
# minutes/hours) - this is background "freshness", not a new headline
# story competing with DocuWare/the live-triggerable scenarios.
POOL = [
    ("Kurzzeitige Verzögerung bei Jira-Benachrichtigungen",
     "Benachrichtigungen",
     "E-Mail- und Push-Benachrichtigungen aus Jira kamen für rund 20 Minuten "
     "verzögert an. Tickets selbst waren jederzeit normal erreichbar. Ursache "
     "war ein kurzzeitig überlasteter Benachrichtigungsdienst, der sich von "
     "selbst erholt hat."),
    ("Kalenderfreigaben kurzzeitig nicht sichtbar",
     "Kalender & Terminfreigabe",
     "Freigegebene Kalender von Kolleginnen und Kollegen waren für kurze Zeit "
     "nicht sichtbar - eigene Termine und Einladungen waren davon nicht "
     "betroffen. Der Synchronisationsdienst wurde neu gestartet, seither "
     "läuft alles wie gewohnt."),
    ("VPN-Neuverbindung zeitweise erforderlich",
     "VPN-Zugang",
     "Ein Teil der Nutzenden musste sich einmalig neu mit dem VPN verbinden, "
     "nachdem ein Zertifikat auf dem VPN-Gateway turnusgemäß erneuert wurde. "
     "Kein Datenverlust, keine Sicherheitsauswirkung."),
    ("Blueant kurzzeitig langsam",
     "Blueant",
     "Blueant reagierte für etwa 10 Minuten spürbar langsamer als gewohnt. "
     "Ursache war ein einzelner stark ausgelasteter Anwendungsserver, der "
     "automatisch aus dem Lastverbund genommen wurde."),
    ("WLAN-Aussetzer im Hauptgebäude",
     "WLAN",
     "Im Hauptgebäude kam es für wenige Minuten zu vereinzelten "
     "WLAN-Verbindungsabbrüchen. Ein Access Point hatte sich aufgehängt und "
     "wurde automatisch neu gestartet."),
    ("Datei-Anhänge in Jira kurzzeitig langsam",
     "Anhänge & Dateien",
     "Das Hoch- und Herunterladen von Datei-Anhängen in Jira war für kurze "
     "Zeit deutlich langsamer als gewohnt. Tickets, Kommentare und die Suche "
     "waren davon nicht betroffen."),
]


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


def load_state():
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"rotating": []}  # list of {"title": ..., "incidentId": ..., "createdAt": iso}


def save_state(state):
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2)


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

severities = get_list("incident-severity")
minor_severity_id = next((s["_id"] for s in severities if "Minor" in s.get("name", "")),
                         severities[0]["_id"])
resolved_state_id = next(
    s["_id"] for s in get_list("incident-state", select={"_id": True, "isResolvedState": True})
    if s.get("isResolvedState"))

state = load_state()
rotating = state.get("rotating", [])

# Retire the oldest entries once the rotating set would exceed MAX_ROTATING
# after adding a new one - deleted outright (not just marked Resolved,
# they already are) so the status page's incident history doesn't grow
# forever across months of daily runs.
while len(rotating) >= MAX_ROTATING:
    oldest = rotating.pop(0)
    call(f"/api/incident/{oldest['incidentId']}", None, method="DELETE")
    print(f"    retired '{oldest['title']}'")

used_titles = {r["title"] for r in rotating}
candidates = [p for p in POOL if p[0] not in used_titles] or list(POOL)
title, monitor_name, description = random.choice(candidates)

monitor = find_by_name("monitor", monitor_name)
if not monitor:
    sys.exit(f"ERROR: monitor '{monitor_name}' not found - run ./seed-oneuptime.sh first.")

# Declared a few hours ago and already resolved - reads as "something
# minor happened today and got handled quickly", not a currently-active
# problem.
declared_at = datetime.now() - timedelta(hours=random.randint(2, 9))
payload = {
    "title": title,
    "description": description,
    "incidentSeverityId": minor_severity_id,
    "currentIncidentStateId": resolved_state_id,
    "monitors": [entity_ref(monitor["_id"])],
    "declaredAt": iso(declared_at),
    "projectId": project_id,
}
created = call("/api/incident", {"data": payload})
rotating.append({"title": title, "incidentId": created["_id"], "createdAt": iso(datetime.now())})
save_state({"rotating": rotating})
print(f"==> Added '{title}' (resolved, {declared_at.strftime('%d.%m. %H:%M')}) - "
      f"{len(rotating)}/{MAX_ROTATING} rotating incidents now active.")
