#!/usr/bin/env python3
"""Seeds a ready-to-show OneUptime instance for the cert-monitoring demo.

Invoked by ../seed-oneuptime.sh, which sets the environment variables this
script reads and restarts oneuptime-sync afterwards. Not meant to be run
standalone (it reads/writes ../.env relative to the current directory,
which the wrapper cds into before calling this).

Idempotent and convergent: re-running reuses existing account, project,
monitors, groups and status pages (matched by name, or by monitorId for
status-page-resources) and updates them onto the current texts/settings,
instead of creating duplicates. Objects from older versions of this
script are renamed in place rather than duplicated (see LEGACY_NAMES).

All demo dates (printer maintenance, patchday, firewall announcement)
are computed relative to "now" at run time - re-running the script keeps
the demo's scheduled events in the future / currently ongoing, instead of
drifting into the past.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = os.environ["OU_BASE"]
SYNC_BASE = os.environ["OU_SYNC_BASE"]
EMAIL = os.environ["OU_EMAIL"]
PASSWORD = os.environ["OU_PASSWORD"]
PROJECT_NAME = os.environ["OU_PROJECT"]
HEARTBEAT_MINUTES = int(os.environ["HEARTBEAT_MINUTES"])

# The seeded content is German on purpose: this demo is presented to
# German-speaking app owners and end users, and the status page is the
# part they actually see.
DEMO_MONITOR_NAME = "Demo-Website (Zertifikats-Fixture)"
# Three separate pages, three different cases on purpose (not one page
# with everything mixed in): STATUS_PAGE_NAME stays a narrow showcase of
# certificate/website monitoring itself (raw target URLs); IT_SERVICE_PAGE
# is the "can I do my work right now" employee-facing service view
# (Jira/Outlook/DocuWare/static services, patch days); LEIPZIG_PAGE is a
# site/facility-specific case (Internet/Netzwerk/WLAN/Drucker).
STATUS_PAGE_NAME = "Statusseite Zertifikats-Monitoring"
IT_SERVICE_PAGE_NAME = "Statusseite IT-Services (Mitarbeiter)"
LEIPZIG_PAGE_NAME = "Statusseite Standort Leipzig"
ENV_FILE = ".env"

# Plain-text names replacing this script's earlier emoji-prefixed ones
# (too playful for the intended audience). Passed as `legacy` so a
# previously-emoji monitor is renamed in place instead of duplicated.
EMOJI_RENAMES = {
    "Anmeldung & Ticket-Suche": ["📋 Anmeldung & Ticket-Suche"],
    "Benachrichtigungen": ["🔔 Benachrichtigungen"],
    "Anhänge & Dateien": ["📎 Anhänge & Dateien"],
    "E-Mail senden/empfangen": ["📧 E-Mail senden/empfangen"],
    "Kalender & Terminfreigabe": ["📅 Kalender & Terminfreigabe"],
    "Anmeldung (SSO)": ["🔑 Anmeldung (SSO)"],
    "VPN-Zugang": ["🔒 VPN-Zugang"],
    "Finanzapplikationen": ["💶 Finanzapplikationen"],
    "Projektmanagement-Tools": ["📊 Projektmanagement-Tools"],
    "Blueant": ["📇 Blueant"],
    "DocuWare (Dokumentenmanagement)": ["🗂️ DocuWare (Dokumentenmanagement)"],
    "Internet-Anbindung": ["🌐 Internet-Anbindung"],
    "Netzwerk (LAN)": ["🔌 Netzwerk (LAN)"],
    "WLAN": ["📶 WLAN"],
    "Drucker (Hauptgebäude)": ["🖨️ Drucker (Hauptgebäude)"],
    "OpenShift-Cluster": ["🧭 OpenShift-Cluster"],
    "MSSQL-Datenbanken": ["🗄️ MSSQL-Datenbanken"],
    "VMware-Umgebung": ["🖥️ VMware-Umgebung"],
    "Server (Windows/Linux)": ["🖳 Server (Windows/Linux)"],
    "Storage (SAN/NAS)": ["💾 Storage (SAN/NAS)"],
    "Netzwerk-Backbone": ["🌐 Netzwerk-Backbone"],
    "Modell-Verfügbarkeit": ["🤖 Modell-Verfügbarkeit"],
    "Latenz & Durchsatz": ["⚡ Latenz & Durchsatz"],
    "GPU-Auslastung": ["🎮 GPU-Auslastung"],
    "Guardrails & Fehlerquote": ["🛡️ Guardrails & Fehlerquote"],
    "Kosten & Nutzung": ["📊 Kosten & Nutzung"],
}

# Names used by earlier versions of this script. Found objects are renamed
# rather than duplicated, so re-running after the rename stays idempotent.
LEGACY_NAMES = {
    "project": ["Cert Monitoring Demo"],
    "status-page": ["Cert Monitoring Demo Status"],
    "monitor": ["Demo Broken Site (cert fixture)"],
}

token = None
project_id = None


# ── Generic API helpers ──────────────────────────────────────────────────────
def call(path, payload, method="POST"):
    """Send JSON to the OneUptime API. Raises RuntimeError on an API error."""
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if project_id:
        req.add_header("ProjectID", project_id)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise RuntimeError(f"{path} -> HTTP {exc.code}: {body[:300]}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{path} -> not reachable: {exc.reason}") from None
    parsed = json.loads(body) if body else {}
    if isinstance(parsed, dict) and "error" in parsed:
        raise RuntimeError(f"{path} -> {parsed['error']}")
    return parsed


def typed(t, v):
    return {"_type": t, "value": v}


def entity_ref(obj_id):
    """Reference to an existing row for an EntityArray relation field
    (e.g. ScheduledMaintenance.monitors, StatusPageAnnouncement.statusPages):
    OneUptime's generic fromJSON only needs the bare `_id` per element."""
    return {"_id": obj_id}


def get_list(model, query=None, select=None, limit=100):
    return call(
        f"/api/{model}/get-list",
        {"query": query or {}, "select": select or {"_id": True, "name": True},
         "sort": {}, "skip": 0, "limit": limit},
    ).get("data", [])


def find_by_name(model, name, select=None, legacy=None, query=None, name_field="name"):
    """Find by name (optionally scoped by `query`); fall back to this
    script's previous English names and rename in place, so an older
    seeded instance converges instead of ending up with both variants
    side by side.

    name_field: some models use "title" instead of "name" (ScheduledMaintenance,
    StatusPageAnnouncement) - pass name_field="title" for those."""
    select = select or {"_id": True, name_field: True}
    rows = get_list(model, query=query, select=select)
    for row in rows:
        if row.get(name_field) == name:
            return row
    for old in (legacy or LEGACY_NAMES.get(model, [])):
        for row in rows:
            if row.get(name_field) == old:
                call(f"/api/{model}/{row['_id']}", {"data": {name_field: name}}, method="PUT")
                print(f"    renamed '{old}' -> '{name}'")
                row[name_field] = name
                return row
    return None


# ── Date helpers ──────────────────────────────────────────────────────────────
WEEKDAY_NAMES_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
                     "Samstag", "Sonntag"]


def next_weekday_at(target_weekday, hour, minute=0, strictly_future=True):
    """The next occurrence of `target_weekday` (0=Monday..6=Sunday) at the
    given time. If today already is that weekday, rolls to next week when
    strictly_future=True - a "kommenden Freitag" maintenance notice should
    never land on today with no notice."""
    now = datetime.now()
    days_ahead = (target_weekday - now.weekday()) % 7
    if days_ahead == 0 and strictly_future:
        days_ahead = 7
    target_date = (now + timedelta(days=days_ahead)).date()
    return datetime(target_date.year, target_date.month, target_date.day, hour, minute)


def next_week_monday():
    """Monday of the week after the current one."""
    now = datetime.now()
    days_ahead = (0 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = (now + timedelta(days=days_ahead)).date()
    return datetime(target_date.year, target_date.month, target_date.day)


def fmt_de(dt):
    return f"{WEEKDAY_NAMES_DE[dt.weekday()]}, {dt.strftime('%d.%m.%Y')}, {dt.strftime('%H:%M')} Uhr"


def iso(dt):
    # Date/DateTime columns on ScheduledMaintenance/StatusPageAnnouncement
    # take a plain ISO string directly - wrapping it as {"_type":"Date",...}
    # (needed for other typed fields elsewhere in this script) makes the
    # object literal reach Postgres unparsed: "invalid input syntax for
    # type timestamp with time zone" (confirmed via oneuptime-app-1 logs).
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ── Account ─────────────────────────────────────────────────────────────────
creds = {"email": typed("Email", EMAIL), "password": typed("HashedString", PASSWORD)}
try:
    call("/api/identity/signup", {"data": dict(
        creds, name=typed("Name", "Demo Admin"),
        companyName=typed("Name", PROJECT_NAME))})
    print(f"==> Created account {EMAIL}")
except RuntimeError as exc:
    # An existing account is the normal case on a re-run. Any other signup
    # failure is only reported here, not fatal: the login below is the real
    # gate and fails with a precise message if the account is unusable.
    if "already" in str(exc).lower() or "exist" in str(exc).lower():
        print(f"==> Account {EMAIL} already exists")
    else:
        print(f"    WARNING: signup failed ({exc}) - trying to log in anyway")

login = call("/api/identity/login", {"data": creds})
token = login.get("_miscData", {}).get("accessToken")
if not token:
    sys.exit(f"ERROR: login for {EMAIL} failed - wrong password? Response: {str(login)[:200]}")
print(f"==> Logged in as {EMAIL}")

# ── Project ─────────────────────────────────────────────────────────────────
existing = find_by_name("project", PROJECT_NAME)
if existing:
    project_id = existing["_id"]
    print(f"==> Reusing project '{PROJECT_NAME}'")
else:
    project_id = call("/api/project", {"data": {"name": PROJECT_NAME}})["_id"]
    print(f"==> Created project '{PROJECT_NAME}'")

# ── Status / severity ids used by monitor criteria and manual overrides ─────
statuses = get_list("monitor-status", select={"_id": True, "name": True,
                                              "isOperationalState": True, "isOfflineState": True})
operational = next(s["_id"] for s in statuses if s.get("isOperationalState"))
offline = next(s["_id"] for s in statuses if s.get("isOfflineState"))
degraded = next((s["_id"] for s in statuses
                  if not s.get("isOperationalState") and not s.get("isOfflineState")),
                 operational)
severities = get_list("incident-severity")
severity = next((s["_id"] for s in severities if "Major" in s.get("name", "")), severities[0]["_id"])


# ── Monitors ──────────────────────────────────────────────────────────────────
def heartbeat_monitor_steps(name):
    """Heartbeat semantics: no ping within N minutes -> Offline + incident,
    a ping within N minutes -> Operational. Note the upstream spelling
    'Recieved' - it is the literal enum value and must match exactly.

    The incident title/description are what end users read on the public
    status page, so they are German like the rest of the page."""
    return typed("MonitorStep", {
        "id": "00000000-0000-4000-8000-000000000001",
        "monitorCriteria": typed("MonitorCriteria", {"monitorCriteriaInstanceArray": [
            typed("MonitorCriteriaInstance", {
                "id": "00000000-0000-4000-8000-000000000002",
                "monitorStatusId": offline,
                "filterCondition": "Any",
                "filters": [{"checkOn": "Incoming Request",
                             "filterType": "Not Recieved In Minutes",
                             "value": HEARTBEAT_MINUTES}],
                "incidents": [{"title": f"{name} ist offline",
                               "description":
                                   f"Seit {HEARTBEAT_MINUTES} Minuten ist kein Heartbeat "
                                   f"für {name} eingegangen. Die Überwachung meldet das Ziel "
                                   f"als nicht erreichbar oder das TLS-Zertifikat als "
                                   f"abgelaufen. Die IT arbeitet an der Behebung.",
                               "incidentSeverityId": severity,
                               "autoResolveIncident": True,
                               "id": "00000000-0000-4000-8000-000000000003",
                               "onCallPolicyIds": []}],
                "alerts": [], "createAlerts": False,
                "changeMonitorStatus": True, "createIncidents": True,
                "name": f"Prüfen, ob {name} offline ist",
                "description": f"Kein Heartbeat seit {HEARTBEAT_MINUTES} Minuten",
            }),
            typed("MonitorCriteriaInstance", {
                "id": "00000000-0000-4000-8000-000000000004",
                "monitorStatusId": operational,
                "filterCondition": "All",
                "filters": [{"checkOn": "Incoming Request",
                             "filterType": "Recieved In Minutes",
                             "value": HEARTBEAT_MINUTES}],
                "incidents": [], "alerts": [], "createAlerts": False,
                "changeMonitorStatus": True, "createIncidents": False,
                "name": f"Prüfen, ob {name} online ist",
                "description": f"Heartbeat innerhalb von {HEARTBEAT_MINUTES} Minuten empfangen",
            }),
        ]}),
        "requestType": "GET",
    })


SELECT_MONITOR = {"_id": True, "name": True, "incomingRequestSecretKey": True}
monitor_ids = {}  # name -> id, filled in as monitors are created/found below


def ensure_heartbeat_monitor(name, description):
    """Incoming-Request monitor fed by oneuptime-sync (real Prometheus probe
    behind it). Returns the monitor id; also records its heartbeat URL."""
    steps = typed("MonitorSteps", {"monitorStepsInstanceArray": [heartbeat_monitor_steps(name)]})
    found = find_by_name("monitor", name, select=SELECT_MONITOR)
    if found:
        call(f"/api/monitor/{found['_id']}",
             {"data": {"description": description, "monitorSteps": steps}}, method="PUT")
        secret = found.get("incomingRequestSecretKey")
        print(f"    updated monitor '{name}'")
        monitor_id = found["_id"]
    else:
        created = call("/api/monitor", {"data": {
            "name": name, "projectId": project_id,
            "monitorType": "Incoming Request",
            "description": description,
            "monitorSteps": steps,
        }})
        secret = created.get("incomingRequestSecretKey")
        print(f"    created monitor '{name}'")
        monitor_id = created["_id"]
    if isinstance(secret, dict):
        secret = secret.get("value")
    if not secret:
        sys.exit(f"ERROR: no incomingRequestSecretKey for monitor '{name}'")
    monitor_ids[name] = monitor_id
    return monitor_id, secret


def ensure_manual_monitor(name, description):
    """A monitor with no sensor at all (MonitorType.Manual): OneUptime
    never probes it and it has no criteria, so it just keeps whatever
    status it's given - new monitors start Operational automatically
    (MonitorService.onBeforeCreate), which is exactly the "always green,
    no sensor" behaviour these resources need."""
    found = find_by_name("monitor", name, select={"_id": True, "name": True},
                         legacy=EMOJI_RENAMES.get(name))
    if found:
        call(f"/api/monitor/{found['_id']}", {"data": {"description": description}}, method="PUT")
        print(f"    updated monitor '{name}'")
        monitor_id = found["_id"]
    else:
        created = call("/api/monitor", {"data": {
            "name": name, "projectId": project_id,
            "monitorType": "Manual",
            "description": description,
        }})
        print(f"    created monitor '{name}'")
        monitor_id = created["_id"]
    monitor_ids[name] = monitor_id
    return monitor_id


def set_monitor_status(monitor_id, status_id):
    call(f"/api/monitor/{monitor_id}", {"data": {"currentMonitorStatusId": status_id}}, method="PUT")


# ── Status pages & groups ────────────────────────────────────────────────────
def ensure_status_page(name, page_title, description, extra_settings=None):
    settings = {
        "pageTitle": page_title,
        "description": description,
        "isPublicStatusPage": True,
        "defaultLanguage": "de",
        "showIncidentsOnStatusPage": True,
        "showIncidentHistoryInDays": 30,
        "showAnnouncementsOnStatusPage": True,
        "showScheduledMaintenanceEventsOnStatusPage": True,
        "showScheduledEventHistoryInDays": 30,
        "showOverallUptimePercentOnStatusPage": True,
    }
    if extra_settings:
        settings.update(extra_settings)
    page = find_by_name("status-page", name)
    if page:
        call(f"/api/status-page/{page['_id']}", {"data": settings}, method="PUT")
        print(f"==> Updated status page '{name}'")
        return page["_id"]
    page_id = call("/api/status-page", {"data": dict(settings, name=name, projectId=project_id)})["_id"]
    print(f"==> Created status page '{name}'")
    return page_id


def ensure_group(page_id, name, order, description=None):
    found = find_by_name("status-page-group", name, select={"_id": True, "name": True},
                          query={"statusPageId": page_id}, legacy=[])
    payload = {"statusPageId": page_id, "projectId": project_id, "name": name, "order": order}
    if description:
        payload["description"] = description
    if found:
        call(f"/api/status-page-group/{found['_id']}", {"data": payload}, method="PUT")
        return found["_id"]
    created = call("/api/status-page-group", {"data": payload})
    print(f"    created group '{name}'")
    return created["_id"]


def _resource_monitor_id(row):
    value = row.get("monitorId")
    return value.get("value") if isinstance(value, dict) else value


def attach_resource(page_id, monitor_id, display_name, order, group_id=None, display_description=None):
    """Adds (or relabels/regroups) a monitor on a status page. Matched by
    monitorId, not by displayName: a renamed monitor still carries its old
    displayName here, and OneUptime rejects adding the same monitor twice -
    so matching on the name would try to re-add it and fail instead of
    just updating the existing entry."""
    existing_resources = get_list("status-page-resource", query={"statusPageId": page_id},
                                   select={"_id": True, "displayName": True, "monitorId": True})
    by_monitor = {_resource_monitor_id(r): r for r in existing_resources}
    existing = by_monitor.get(monitor_id)
    payload = {"displayName": display_name, "order": order}
    if group_id is not None:
        payload["statusPageGroupId"] = group_id
    if display_description is not None:
        payload["displayDescription"] = display_description
    if existing:
        needs_update = (existing.get("displayName") != display_name)
        if needs_update:
            call(f"/api/status-page-resource/{existing['_id']}", {"data": payload}, method="PUT")
            print(f"    updated status page entry '{display_name}'")
        else:
            call(f"/api/status-page-resource/{existing['_id']}", {"data": payload}, method="PUT")
        return existing["_id"]
    created = call("/api/status-page-resource", {"data": dict(
        payload, statusPageId=page_id, projectId=project_id, monitorId=monitor_id,
        showCurrentStatus=True, showUptimePercent=True, showStatusHistoryChart=True)})
    print(f"    added '{display_name}' to the status page")
    return created["_id"]


# ── Branding: one distinct SVG logo per page (uploaded as a File, set via
# StatusPage.logoFileId) ────────────────────────────────────────────────────
# headerHTML/footerHTML/customCSS on StatusPage are documented as "served
# only from a verified custom domain" - useless on this demo's plain
# localhost URL. logoFileId has no such restriction (confirmed live: the
# uploaded file serves at /api/file/image/<id> regardless of domain), so
# it's the one branding lever that actually renders here. Professional
# and simple on purpose - the emoji-per-row approach above was explicitly
# rejected as too playful; this keeps visual identity to one clean mark
# per page instead of scattering icons through the list.
LOGOS = {
    "cert": ("#0f6cbd",
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">'
        '<rect width="120" height="120" rx="20" fill="#0f6cbd"/>'
        '<path d="M60 22 L92 34 V58 C92 80 78 96 60 104 C42 96 28 80 28 58 V34 Z" '
        'fill="none" stroke="#ffffff" stroke-width="5"/>'
        '<path d="M46 62 L56 72 L76 48" fill="none" stroke="#ffffff" stroke-width="6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'),
    "itservice": ("#0e7a4d",
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">'
        '<rect width="120" height="120" rx="20" fill="#0e7a4d"/>'
        '<rect x="30" y="34" width="60" height="40" rx="8" fill="none" stroke="#fff" stroke-width="5"/>'
        '<path d="M46 74 L46 90 L64 74" fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round"/>'
        '<circle cx="48" cy="54" r="3.5" fill="#fff"/><circle cx="60" cy="54" r="3.5" fill="#fff"/>'
        '<circle cx="72" cy="54" r="3.5" fill="#fff"/></svg>'),
    "leipzig": ("#c25a00",
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">'
        '<rect width="120" height="120" rx="20" fill="#c25a00"/>'
        '<path d="M60 26 C46 26 35 37 35 51 C35 71 60 96 60 96 C60 96 85 71 85 51 C85 37 74 26 60 26 Z" '
        'fill="#fff"/><circle cx="60" cy="51" r="11" fill="#c25a00"/></svg>'),
}


def ensure_page_logo(key, page_id):
    """Uploads (once) and assigns a logo File for a status page. Reuses the
    file id from a local marker (.oneuptime-logo-<key>.id) across runs -
    File rows are immutable in OneUptime (no update permission), and this
    demo doesn't need a fresh upload every time nothing changed."""
    marker = f".oneuptime-logo-{key}.id"
    file_id = None
    if os.path.exists(marker):
        candidate = open(marker).read().strip()
        try:
            urllib.request.urlopen(f"{BASE}/api/file/image/{candidate}", timeout=10)
            file_id = candidate
        except urllib.error.URLError:
            pass
    if not file_id:
        _color, svg = LOGOS[key]
        svg_bytes = svg.encode()
        created = call("/api/file", {"data": {
            "name": f"logo-{key}.svg", "fileType": "image/svg+xml", "isPublic": True,
            "file": {"_type": "Buffer", "value": {"type": "Buffer", "data": list(svg_bytes)}},
        }})
        file_id = created["_id"]
        with open(marker, "w") as fh:
            fh.write(file_id)
        print(f"    uploaded logo for '{key}'")
    call(f"/api/status-page/{page_id}", {"data": {"logoFileId": file_id}}, method="PUT")


# ── 1) Zertifikats-Monitoring: reiner Showcase für Website-/Zertifikats-
# Überwachung (rohe Ziel-URLs aus DEMO_TARGET_URLS) - bewusst KEINE
# Mitarbeiter-Dienste hier, die leben auf der IT-Service-Seite unten. ───────
def env_value(key):
    with open(ENV_FILE) as fh:
        for line in fh:
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


target_urls = [u for u in env_value("DEMO_TARGET_URLS").split(",") if u.strip()]
if not target_urls:
    sys.exit("ERROR: DEMO_TARGET_URLS is empty in .env - nothing to create monitors for.")

# The fixture monitor is kept last and tracked separately: it feeds
# ONEUPTIME_DEMO_HEARTBEAT_URL, which is what break-demo.sh exercises.
wanted = [(u, u.split("//")[-1].split("/")[0]) for u in target_urls]
wanted.append((None, DEMO_MONITOR_NAME))

heartbeats = {}
for url, name in wanted:
    description = ("Heartbeat, gespeist von Prometheus über oneuptime-sync – "
                   + (f"Ziel: {url}" if url else "Zertifikats-Fixture der Demo"))
    _mid, secret = ensure_heartbeat_monitor(name, description)
    heartbeats[name] = f"{SYNC_BASE}/incoming-request-ingest/incoming-request/{secret}"

page_id = ensure_status_page(
    STATUS_PAGE_NAME, "Website- & Zertifikatsstatus",
    "Öffentlicher Status der überwachten Dienste.")
ensure_page_logo("cert", page_id)

for order, (_url, name) in enumerate(wanted, start=1):
    attach_resource(page_id, monitor_ids[name], name, order)

# Prune what no longer belongs here: a target dropped from
# DEMO_TARGET_URLS (e.g. the original www.google.com/github.com/
# wikipedia.org placeholders, replaced by real targets since) otherwise
# lingers forever as an orphaned resource AND monitor - nothing before
# this ever removed stale entries, only added/updated current ones. Also
# drops any status-page-group left over here from before the IT-Service
# page existed: this page is a flat, ungrouped raw-URL showcase now.
keep_monitor_ids = {monitor_ids[name] for _u, name in wanted}
for r in get_list("status-page-resource", query={"statusPageId": page_id},
                  select={"_id": True, "monitorId": True, "displayName": True}):
    mid = _resource_monitor_id(r)
    if mid not in keep_monitor_ids:
        call(f"/api/status-page-resource/{r['_id']}", None, method="DELETE")
        call(f"/api/monitor/{mid}", None, method="DELETE")
        print(f"    removed stale target '{r.get('displayName')}' (no longer in DEMO_TARGET_URLS)")
for g in get_list("status-page-group", query={"statusPageId": page_id}, select={"_id": True, "name": True}):
    call(f"/api/status-page-group/{g['_id']}", None, method="DELETE")
    print(f"    removed leftover group '{g.get('name')}' from the certificate page")

# ── 2) IT-Services (Mitarbeiter): "Kann ich gerade arbeiten?" - Dienste mit
# ihren Einschränkungen aus Mitarbeitersicht, eigene Statusseite. ───────────
it_service_page_id = ensure_status_page(
    IT_SERVICE_PAGE_NAME, "IT-Services für Mitarbeitende",
    "Aktueller Status der internen IT-Services - zeigt euch, ob ihr eure "
    "Arbeit uneingeschränkt erledigen könnt.")
ensure_page_logo("itservice", it_service_page_id)

jira_group = ensure_group(it_service_page_id, "Aufgabenverwaltung (Jira)", 10,
                          "Status der Ticket- und Aufgabenverwaltung.")
outlook_group = ensure_group(it_service_page_id, "E-Mail & Kalender (Outlook)", 11,
                             "Status von E-Mail, Kalender und Anmeldung.")

JIRA_ITEMS = [
    ("Anmeldung & Ticket-Suche", "Reaktionszeit wie gewohnt"),
    ("Benachrichtigungen", "Zustellung wie gewohnt"),
    ("Anhänge & Dateien", "Hoch-/Download wie gewohnt"),
]
OUTLOOK_ITEMS = [
    ("E-Mail senden/empfangen", "Zustellung wie gewohnt"),
    ("Kalender & Terminfreigabe", "Synchronisation wie gewohnt"),
    ("Anmeldung (SSO)", "Anmeldung wie gewohnt"),
]
for group_id, items, prefix in ((jira_group, JIRA_ITEMS, "jira"), (outlook_group, OUTLOOK_ITEMS, "outlook")):
    for i, (name, sub) in enumerate(items, start=1):
        mid = ensure_manual_monitor(name, f"Nutzerfreundlicher Statuseintrag ({prefix})")
        attach_resource(it_service_page_id, mid, name, 20 + i, group_id=group_id, display_description=sub)

static_group = ensure_group(it_service_page_id, "Weitere interne Dienste", 30,
                            "Dienste ohne aktive Überwachung - Status wird manuell gepflegt.")
STATIC_SERVICES = [
    ("VPN-Zugang", "Verbindungsqualität: sehr gut"),
    ("Finanzapplikationen", "Antwortzeit: normal"),
    ("Projektmanagement-Tools", "Antwortzeit: schnell"),
    ("Blueant", "Antwortzeit: normal"),
]
for i, (name, sub) in enumerate(STATIC_SERVICES, start=1):
    mid = ensure_manual_monitor(name, "Statischer Diensteintrag ohne Sensor")
    attach_resource(it_service_page_id, mid, name, 40 + i, group_id=static_group, display_description=sub)

blueant_monitor_id = monitor_ids["Blueant"]

# DocuWare-Cluster: einfache Nutzeransicht + Major Incident. Deliberately a
# Manual monitor, NOT the demo-broken-site-style heartbeat: the whole
# point of this example is "site reachable, login broken" - a distinction
# blackbox HTTP probing can't make anyway. A heartbeat-driven monitor
# would auto-heal back to Operational on the next successful ping (the
# fixture IS reachable) and fight the manual "Degraded" below, and would
# also auto-create its own "kein Heartbeat" incident alongside the
# hand-written Major Incident - two conflicting incidents for one story.
# Manual keeps a single, consistent narrative: the incident IS the signal.
DOCUWARE_MONITOR_NAME = "DocuWare (Dokumentenmanagement)"
docuware_monitor_id = ensure_manual_monitor(
    DOCUWARE_MONITOR_NAME,
    "Interne Nutzung durch Mitarbeitende - Status folgt dem Incident, nicht der reinen "
    "Erreichbarkeit (siehe Grafana-Dashboard für die technische Tiefe).")

# Second, separate entry for the customer-facing side: the login incident
# below only breaks the internal DocuWare backend staff use - invoice
# retrieval for the ~1,000,000 customers keeps working (see the customer
# portal traffic in the Grafana dashboard, which stays live either way).
# Splitting this into its own status-page row is the point: staff fielding
# a customer call needs to be able to say, at a glance, "that part is
# fine" instead of one conflated DocuWare status covering both.
DOCUWARE_PORTAL_MONITOR_NAME = "DocuWare-Kundenportal (Rechnungsabruf)"
docuware_portal_monitor_id = ensure_manual_monitor(
    DOCUWARE_PORTAL_MONITOR_NAME,
    "Rechnungsabruf für Kundinnen und Kunden - unabhängig vom internen Backend-Login.")

docuware_group = ensure_group(it_service_page_id, "Dokumentenmanagement", 5,
                              "DocuWare: interne Nutzung und Kundenportal getrennt "
                              "ausgewiesen, damit ihr bei Kundenrückfragen sofort seht, "
                              "welcher Teil betroffen ist.")
attach_resource(it_service_page_id, docuware_monitor_id, DOCUWARE_MONITOR_NAME, 6,
                group_id=docuware_group, display_description="Für die interne Bearbeitung")
attach_resource(it_service_page_id, docuware_portal_monitor_id, DOCUWARE_PORTAL_MONITOR_NAME, 7,
                group_id=docuware_group, display_description="Für Kundenrückfragen zum Rechnungsabruf")

# Custom ITIL-v4-style state for the remediation phase. OneUptime seeds
# only Identified/Acknowledged/Resolved by default (ProjectService
# addDefaultIncidentState) - "In Behebung" sits between Acknowledged and
# Resolved and is neither, so the incident shows as actively worked on
# rather than merely noticed or already fixed.
incident_states = get_list("incident-state",
                           select={"_id": True, "name": True, "order": True,
                                   "isAcknowledgedState": True, "isResolvedState": True})
in_remediation = find_by_name("incident-state", "In Behebung",
                              select={"_id": True, "name": True}, legacy=[])
if in_remediation:
    in_remediation_id = in_remediation["_id"]
else:
    resolved_order = next((s["order"] for s in incident_states if s.get("isResolvedState")), 3)
    # order is a smallint column with server-side auto-reordering
    # (IncidentStateService.rearrangeOrder): inserting at Resolved's
    # current integer order pushes Resolved (and anything after it) down
    # by one, landing "In Behebung" right before it. A fractional
    # midpoint (e.g. 2.5) fails - Postgres rejects it for smallint.
    in_remediation_id = call("/api/incident-state", {"data": {
        "projectId": project_id, "name": "In Behebung",
        "order": int(resolved_order),
        "color": typed("Color", "#f5a623"),
        "isAcknowledgedState": False, "isResolvedState": False,
    }})["_id"]
    print("    created incident state 'In Behebung'")

BMC_INCIDENT_NUMBER = "INC000000222127"
BMC_INCIDENT_URL = ("https://pyur-smartit.onbmc.com/smartit/app/"
                    "#/incidentPV/IDGBB2EGIWYMIAT1O0TAT1O0TARK3T")
DOCUWARE_INCIDENT_TITLE = "DocuWare | Anmeldung in DocuWare nicht möglich"

existing_incident = find_by_name("incident", DOCUWARE_INCIDENT_TITLE,
                                 select={"_id": True, "title": True}, legacy=[], name_field="title")
incident_payload = {
    "title": DOCUWARE_INCIDENT_TITLE,
    "description":
        "Aktuell können sich Mitarbeitende **nicht bei DocuWare anmelden**. Bereits "
        "geöffnete Dokumente bleiben nutzbar, ein Neustart der Anwendung führt jedoch "
        "zu einer Fehlermeldung beim Login. Die IT arbeitet an der Behebung.\n\n"
        "**Betroffen ist ausschließlich das interne DocuWare-Backend** für "
        "Mitarbeitende, die dort direkt arbeiten. Der **Rechnungsabruf für "
        "Kundinnen und Kunden ist nicht betroffen** und funktioniert normal - "
        "bei Kundenrückfragen dazu könnt ihr das so beantworten.\n\n"
        f"**Referenz:** BMC Incident [{BMC_INCIDENT_NUMBER}]({BMC_INCIDENT_URL})",
    "incidentSeverityId": severity,
    "currentIncidentStateId": in_remediation_id,
    "monitors": [entity_ref(docuware_monitor_id)],
}
if existing_incident:
    call(f"/api/incident/{existing_incident['_id']}", {"data": incident_payload}, method="PUT")
    print(f"==> Updated incident '{DOCUWARE_INCIDENT_TITLE}'")
else:
    incident_payload["projectId"] = project_id
    call("/api/incident", {"data": incident_payload})
    print(f"==> Created incident '{DOCUWARE_INCIDENT_TITLE}' (In Behebung)")

# A "major incident: login broken" story next to a green monitor reads as
# contradictory - reflect it on the status page too. "Degraded" (not
# Offline): the site itself stays reachable, only the login flow is down.
set_monitor_status(docuware_monitor_id, degraded)

# ── 3) Standort Leipzig (eigene Statusseite, eigener Case: standortbezogene
# Facility-IT statt firmenweiter Dienste) ────────────────────────────────────
leipzig_page_id = ensure_status_page(
    LEIPZIG_PAGE_NAME, "Standort Leipzig – Infrastrukturstatus",
    "Öffentlicher Status der lokalen Infrastruktur am Standort Leipzig.")
ensure_page_logo("leipzig", leipzig_page_id)

LEIPZIG_SERVICES = ["Internet-Anbindung", "Netzwerk (LAN)", "WLAN"]
for i, name in enumerate(LEIPZIG_SERVICES, start=1):
    mid = ensure_manual_monitor(name, "Statischer Diensteintrag ohne Sensor (Standort Leipzig)")
    attach_resource(leipzig_page_id, mid, name, i, display_description="Alle Systeme normal")

printer_name = "Drucker (Hauptgebäude)"
printer_monitor_id = ensure_manual_monitor(printer_name, "Statischer Diensteintrag ohne Sensor (Standort Leipzig)")
attach_resource(leipzig_page_id, printer_monitor_id, printer_name, 4, display_description="Alle Systeme normal")

# ── 4) Geplante Wartungen + Ankündigung (dynamisch datiert) ──────────────────
sm_states = get_list("scheduled-maintenance-state",
                     select={"_id": True, "name": True, "isScheduledState": True,
                             "isOngoingState": True, "isResolvedState": True})
sm_scheduled = next(s["_id"] for s in sm_states if s.get("isScheduledState"))
sm_ongoing = next(s["_id"] for s in sm_states if s.get("isOngoingState"))
sm_completed = next(s["_id"] for s in sm_states if s.get("isResolvedState"))


def ensure_scheduled_maintenance(title, description, starts_at, ends_at, state_id, monitor_ids_list,
                                 status_page_ids):
    found = find_by_name("scheduled-maintenance", title, select={"_id": True, "title": True},
                     legacy=[], name_field="title")
    payload = {
        "title": title, "description": description,
        "startsAt": iso(starts_at), "endsAt": iso(ends_at),
        "currentScheduledMaintenanceStateId": state_id,
        "monitors": [entity_ref(m) for m in monitor_ids_list],
        "statusPages": [entity_ref(p) for p in status_page_ids],
        "shouldStatusPageSubscribersBeNotifiedOnEventCreated": False,
    }
    if found:
        call(f"/api/scheduled-maintenance/{found['_id']}", {"data": payload}, method="PUT")
        print(f"==> Updated scheduled maintenance '{title}'")
        return found["_id"]
    payload["projectId"] = project_id
    created = call("/api/scheduled-maintenance", {"data": payload})
    print(f"==> Created scheduled maintenance '{title}'")
    return created["_id"]


now = datetime.now()

# Patchday: framed as happening right now regardless of when the seed
# script runs, so the demo always shows it as an active disruption.
patchday_start = now - timedelta(hours=2)
patchday_end = now + timedelta(hours=6)
ensure_scheduled_maintenance(
    "Patchday Server Gruppe 3",
    "Im Rahmen des monatlichen Patchdays wird Server-Gruppe 3 aktualisiert und neu "
    "gestartet. **Blueant ist während dieses Zeitfensters gestört** und kann kurzzeitig "
    "nicht erreichbar sein. Alle anderen Dienste sind nicht betroffen. Die IT arbeitet "
    "an der Behebung; ein Update folgt nach Abschluss der Wartung.",
    patchday_start, patchday_end, sm_ongoing, [blueant_monitor_id], [it_service_page_id],
)
set_monitor_status(blueant_monitor_id, degraded)

# VPN-Gateway redundancy test: future, low-impact counterpart to the
# patchday disruption above.
vpn_start = now + timedelta(days=10)
vpn_start = vpn_start.replace(hour=22, minute=0, second=0, microsecond=0)
vpn_end = vpn_start + timedelta(hours=2)
ensure_scheduled_maintenance(
    "Wartungsfenster VPN-Gateway (Redundanz-Test)",
    f"Am {fmt_de(vpn_start)} testet die IT die Ausfallsicherheit des VPN-Gateways durch "
    f"einen geplanten Failover-Test. **Kein Einfluss auf den laufenden Betrieb erwartet** "
    f"- der VPN-Zugang bleibt während des gesamten Zeitfensters nutzbar.",
    vpn_start, vpn_end, sm_scheduled, [], [it_service_page_id],
)

# Completed maintenance on the IT-Service page: narrative predecessor of
# the ongoing "Gruppe 3" patchday above ("Gruppe 1 & 2 already done, no
# issues") - builds the same trust real status pages build by showing a
# track record of maintenance that went fine. Always a few days in the
# past relative to "now", so re-running keeps it looking recent.
patchday12_end = now - timedelta(days=6)
patchday12_start = patchday12_end - timedelta(hours=3)
ensure_scheduled_maintenance(
    "Patchday Server Gruppe 1 & 2",
    "Der monatliche Patchday für Server-Gruppe 1 und 2 wurde planmäßig durchgeführt. "
    "**Keine Auswirkungen** auf die überwachten Dienste - alle Systeme liefen während "
    "der gesamten Wartung normal weiter.",
    patchday12_start, patchday12_end, sm_completed, [], [it_service_page_id],
)

# Completed maintenance on the Leipzig page: same purpose, local-site
# flavour, linked to the network monitor for a bit of narrative
# consistency with the site's live status entries.
switches_end = now - timedelta(days=10)
switches_start = switches_end - timedelta(hours=3)
ensure_scheduled_maintenance(
    "Wartung Netzwerk-Switches (Rechenzentrum Leipzig)",
    "Die geplante Erneuerung der Netzwerk-Switches im Rechenzentrum wurde **erfolgreich "
    "abgeschlossen**. Es gab keine Beeinträchtigungen für Mitarbeitende am Standort.",
    switches_start, switches_end, sm_completed, [monitor_ids["Netzwerk (LAN)"]], [leipzig_page_id],
)

# Printer maintenance: next Friday, framed helpfully for end users
# (what/when/impact/alternative/contact).
printer_start = next_weekday_at(4, 13, 0)  # Friday
printer_end = printer_start.replace(hour=18, minute=0)
ensure_scheduled_maintenance(
    "Wartung Drucker – Hauptgebäude, Standort Leipzig",
    f"Am {fmt_de(printer_start)} bis 18:00 Uhr wird der Drucker im Hauptgebäude gewartet. "
    f"**Bitte nutzt in dieser Zeit den Drucker im 2. OG (Raum 214)** oder den Farbdrucker "
    f"in der Teeküche. Bei dringenden Druckaufträgen wendet euch an den IT-Helpdesk "
    f"(Ext. 4242).",
    printer_start, printer_end, sm_scheduled, [printer_monitor_id], [leipzig_page_id],
)

# Announcement: firewall upgrade window Wed 20:00 - Fri 06:00 next week.
fw_monday = next_week_monday()
fw_start = (fw_monday + timedelta(days=2)).replace(hour=20, minute=0)  # Wednesday
fw_end = (fw_monday + timedelta(days=4)).replace(hour=6, minute=0)     # Friday


def ensure_announcement(title, description, show_at, end_at, status_page_ids):
    found = find_by_name("status-page-announcement", title, select={"_id": True, "title": True},
                     legacy=[], name_field="title")
    payload = {
        "title": title, "description": description,
        "showAnnouncementAt": iso(show_at), "endAnnouncementAt": iso(end_at),
        "statusPages": [entity_ref(p) for p in status_page_ids],
        "shouldStatusPageSubscribersBeNotified": False,
    }
    if found:
        call(f"/api/status-page-announcement/{found['_id']}", {"data": payload}, method="PUT")
        print(f"==> Updated announcement '{title}'")
        return found["_id"]
    payload["projectId"] = project_id
    created = call("/api/status-page-announcement", {"data": payload})
    print(f"==> Created announcement '{title}'")
    return created["_id"]


ensure_announcement(
    "Geplantes Firewall-Upgrade (Barracuda)",
    f"Zwischen **{fmt_de(fw_start)}** und **{fmt_de(fw_end)}** führt die IT ein geplantes "
    f"Upgrade der Barracuda-Firewall durch. Das Zeitfenster liegt außerhalb der "
    f"Kernarbeitszeit; dennoch kann es zu **kurzen, wenige Minuten dauernden "
    f"Unterbrechungen** der Internetverbindung kommen. Ein genauer Termin innerhalb "
    f"des Fensters wird noch bekanntgegeben.",
    now, fw_end, [it_service_page_id, leipzig_page_id],
)

# ── 6) Interne Admin-Sicht: Infrastruktur- und LLM-Observability ────────────
# MonitorGroup/MonitorGroupResource organize monitors on OneUptime's OWN
# internal dashboard - unlike StatusPageGroup, they are never shown on a
# public status page. That's the point here: an example of what an
# admin-facing infrastructure/AI-observability view could look like,
# separate from what end users see. Static/exemplary (Manual monitors,
# no real sensor), same as the earlier "Weitere interne Dienste" group -
# but these deliberately stay technical (admin audience, not end users).
def ensure_monitor_group(name, description=None):
    found = find_by_name("monitor-group", name, select={"_id": True, "name": True}, legacy=[])
    payload = {"projectId": project_id, "name": name}
    if description:
        payload["description"] = description
    if found:
        call(f"/api/monitor-group/{found['_id']}", {"data": payload}, method="PUT")
        return found["_id"]
    created = call("/api/monitor-group", {"data": payload})
    print(f"    created monitor group '{name}'")
    return created["_id"]


def attach_to_monitor_group(group_id, monitor_id):
    existing = get_list("monitor-group-resource", query={"monitorGroupId": group_id},
                        select={"_id": True, "monitorId": True})
    if any(_resource_monitor_id(r) == monitor_id for r in existing):
        return
    call("/api/monitor-group-resource", {"data": {
        "monitorGroupId": group_id, "projectId": project_id, "monitorId": monitor_id,
    }})


infra_group = ensure_monitor_group(
    "Infrastruktur-Monitoring (Admin)",
    "Beispielhafte Admin-Sicht auf zentrale Infrastruktur - nicht auf der "
    "öffentlichen Statusseite sichtbar.")
INFRA_MONITORS = [
    ("OpenShift-Cluster", "Worker-Nodes: 8/8 Ready · Auslastung: 54%"),
    ("MSSQL-Datenbanken", "Cluster-Status: Healthy · Replikations-Lag: 0,3s"),
    ("VMware-Umgebung", "vCenter: Online · Hosts: 12/12 · Auslastung: 61%"),
    ("Server (Windows/Linux)", "1.240 Server überwacht · 3 mit Warnungen"),
    ("Storage (SAN/NAS)", "Kapazität: 68% belegt · Alle Pfade redundant"),
    ("Netzwerk-Backbone", "Alle Kernrouter online · Latenz nominal"),
]
for name, desc in INFRA_MONITORS:
    mid = ensure_manual_monitor(name, desc)
    attach_to_monitor_group(infra_group, mid)

llm_group = ensure_monitor_group(
    "AI / LLM Observability (llm.pyur.com)",
    "Beispielhafte Observability für die interne LLM-Plattform - nicht auf "
    "der öffentlichen Statusseite sichtbar.")
LLM_MONITORS = [
    ("Modell-Verfügbarkeit", "Erreichbarkeit (24h): 100% · Aktive Modelle: 3"),
    ("Latenz & Durchsatz", "P95 Antwortzeit: 480ms · Durchsatz: 1.850 Tokens/Sek."),
    ("GPU-Auslastung", "Cluster-Auslastung: 62% · 8/8 GPUs online"),
    ("Guardrails & Fehlerquote", "Policy-Blocks: 0,4% · Fehlerquote: 0,1%"),
    ("Kosten & Nutzung", "Anfragen heute: 42.300 · Kostentrend: stabil"),
]
for name, desc in LLM_MONITORS:
    mid = ensure_manual_monitor(name, desc)
    attach_to_monitor_group(llm_group, mid)

# ── Write heartbeat URLs back into .env ─────────────────────────────────────
ordered = ",".join(heartbeats[name] for _u, name in wanted if name != DEMO_MONITOR_NAME)
demo_url = heartbeats[DEMO_MONITOR_NAME]

with open(ENV_FILE) as fh:
    lines = fh.readlines()


def set_key(lines, key, value):
    """Set KEY=value, touching only real (uncommented) assignments.

    Commented example lines are documentation and are left alone - an
    earlier version replaced those and left the real, empty assignment
    further down the file, which then won when docker read .env.
    Any duplicate assignments are collapsed onto the first one, for the
    same reason: with two lines the last one silently wins."""
    needle = f"{key}="
    hits = [i for i, line in enumerate(lines) if line.lstrip().startswith(needle)
            and not line.lstrip().startswith("#")]
    if not hits:
        lines.append(f"{key}={value}\n")
        return lines
    lines[hits[0]] = f"{key}={value}\n"
    for i in reversed(hits[1:]):
        del lines[i]
    return lines


lines = set_key(lines, "ONEUPTIME_HEARTBEAT_URLS", ordered)
lines = set_key(lines, "ONEUPTIME_DEMO_HEARTBEAT_URL", demo_url)
with open(ENV_FILE, "w") as fh:
    fh.writelines(lines)
print("==> Wrote ONEUPTIME_HEARTBEAT_URLS and ONEUPTIME_DEMO_HEARTBEAT_URL into .env")

with open(".oneuptime-demo-summary", "w") as fh:
    json.dump({"base": BASE, "email": EMAIL, "projectId": project_id,
               "statusPageId": page_id, "itServiceStatusPageId": it_service_page_id,
               "leipzigStatusPageId": leipzig_page_id,
               "monitors": heartbeats}, fh, indent=1)
print(f"STATUS_PAGE_ID={page_id}")
print(f"IT_SERVICE_STATUS_PAGE_ID={it_service_page_id}")
print(f"LEIPZIG_STATUS_PAGE_ID={leipzig_page_id}")
