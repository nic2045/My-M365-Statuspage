#!/usr/bin/env python3
"""Local control panel for the demo's break-*.sh / fix-*.sh scripts.

Serves a small page (control-panel.html, same directory) with one card
per incident scenario - a short story, an illustration, live status
(read from Prometheus, the stack's own source of truth - no separate
state tracking invented here), and buttons that actually run the
corresponding shell script on the host.

Security: binds to 127.0.0.1 ONLY (never 0.0.0.0) - this executes real
`docker compose exec`/`run` commands via subprocess, so it must never be
reachable from anything but this machine's own browser. The set of
runnable actions is a fixed whitelist mapped 1:1 to the existing,
already-reviewed break-*.sh/fix-*.sh scripts - the API never takes
arbitrary shell input.

Run via ../control-panel.sh (not directly) - that script cds into
demo-cert-monitoring/ first, which this server assumes as its cwd for
both running scripts and querying Prometheus at localhost:9090 (adjust
PROM_URL below if you changed PROMETHEUS_PORT in .env).
"""
import http.server
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

PORT = int(os.environ.get("CONTROL_PANEL_PORT", "7100"))
PROM_URL = os.environ.get("PROM_URL", "http://localhost:9090")
HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_DIR = os.path.dirname(HERE)

# action name -> (script filename, human label) - the only commands this
# server will ever execute.
ACTIONS = {
    "break-demo": ("break-demo.sh", "Zertifikat-Vorfall auslösen"),
    "fix-demo": ("fix-demo.sh", "Zertifikat-Vorfall beheben"),
    "break-docuware": ("break-docuware.sh", "DocuWare-Cluster-Vorfall auslösen"),
    "fix-docuware": ("fix-docuware.sh", "DocuWare-Cluster-Vorfall beheben"),
    "break-docuware-disk": ("break-docuware-disk.sh", "DocuWare-Festplatte-voll-Vorfall auslösen"),
    "fix-docuware-disk": ("fix-docuware-disk.sh", "DocuWare-Festplatte-voll-Vorfall beheben"),
    "break-customer-care": ("break-customer-care.sh", "Customer-Care-Vorfall auslösen"),
    "fix-customer-care": ("fix-customer-care.sh", "Customer-Care-Vorfall beheben"),
    "break-security": ("break-security.sh", "Sicherheits-Vorfall auslösen"),
    "fix-security": ("fix-security.sh", "Sicherheits-Vorfall beheben"),
    "break-printer": ("break-printer.sh", "Druckerwartung ankündigen"),
    "fix-printer": ("fix-printer.sh", "Druckerwartung abschließen"),
    "break-leipzig-network": ("break-leipzig-network.sh", "Leipzig-Netzwerk-Vorfall auslösen"),
    "fix-leipzig-network": ("fix-leipzig-network.sh", "Leipzig-Netzwerk-Vorfall beheben"),
    "break-cognigy": ("break-cognigy.sh", "Cognigy-Vorfall auslösen"),
    "fix-cognigy": ("fix-cognigy.sh", "Cognigy-Vorfall beheben"),
    "break-blueant": ("break-blueant.sh", "Blueant-Vorfall auslösen"),
    "fix-blueant": ("fix-blueant.sh", "Blueant-Vorfall beheben"),
    "break-jira-attachments": ("break-jira-attachments.sh", "Jira-Anhänge-Vorfall auslösen"),
    "fix-jira-attachments": ("fix-jira-attachments.sh", "Jira-Anhänge-Vorfall beheben"),
    "break-leipzig-cascade": ("break-leipzig-cascade.sh", "Kettenreaktion auslösen"),
    "fix-leipzig-cascade": ("fix-leipzig-cascade.sh", "Kettenreaktion beheben"),
    "break-ddos-shop": ("break-ddos-shop.sh", "DDoS-Vorfall auslösen"),
    "fix-ddos-shop": ("fix-ddos-shop.sh", "DDoS-Vorfall beheben"),
}


def prom_query(expr):
    """Returns the first scalar value for a Prometheus instant query, or
    None on any error/empty result - status reporting degrades quietly
    rather than breaking the panel if Prometheus is briefly unreachable."""
    try:
        q = urllib.parse.urlencode({"query": expr})
        with urllib.request.urlopen(f"{PROM_URL}/api/v1/query?{q}", timeout=5) as resp:
            body = json.load(resp)
        result = body.get("data", {}).get("result", [])
        if not result:
            return None
        return float(result[0]["value"][1])
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError):
        return None


def get_links():
    """Reads the OneUptime status-page ids seed-oneuptime.sh already writes
    to .oneuptime-demo-summary, instead of hardcoding them here - they're
    stable across re-runs (find-by-name, not create-new) but this avoids
    ever having a second, driftable copy of the same ids."""
    summary_path = os.path.join(DEMO_DIR, ".oneuptime-demo-summary")
    try:
        with open(summary_path) as fh:
            summary = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        summary = {}

    # Written by docuware_disk_incident.py on every "break" run - the
    # incident id (and so its roles-tab URL) changes each time, so this
    # can't be derived from the stable ids above.
    disk_incident_path = os.path.join(DEMO_DIR, ".docuware-disk-incident.json")
    try:
        with open(disk_incident_path) as fh:
            disk_incident = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        disk_incident = {}

    base = summary.get("base", "http://localhost")
    project_id = summary.get("projectId")
    on_call_policy_id = summary.get("onCallPolicyId")

    # On-Call Duty is otherwise buried several clicks deep in OneUptime's
    # own settings navigation - these two direct links (the configured
    # escalation rule, and the log of every time it has actually fired,
    # e.g. from break-security.sh/break-docuware-disk.sh) are what makes
    # it demoable without hunting for it live.
    on_call_escalation_url = (
        f"{base}/dashboard/{project_id}/on-call-duty/policies/{on_call_policy_id}/escalation"
        if project_id and on_call_policy_id else None)
    on_call_execution_logs_url = (
        f"{base}/dashboard/{project_id}/on-call-duty/policies/{on_call_policy_id}/execution-logs"
        if project_id and on_call_policy_id else None)
    scheduled_maintenance_events_url = (
        f"{base}/dashboard/{project_id}/scheduled-maintenance-events" if project_id else None)

    # Five more OneUptime areas seed_oneuptime.py already builds (Service
    # Catalog, Telemetry Logs, Security Events/Detection Rules, both
    # Monitor Groups) but that otherwise sit unlinked - same "buried
    # several clicks deep" problem as On-Call Duty above. All five are
    # project-scoped list pages, not a specific item, so - unlike the
    # on-call/disk-incident links above - they need no extra id beyond
    # project_id. Routes confirmed against the real OneUptime dashboard
    # source (RouteMap.ts: PageMap.SERVICES, LOGS, SECURITY_EVENTS,
    # SECURITY_EVENTS_DETECTION_RULES, MONITOR_GROUPS), not guessed.
    service_catalog_url = f"{base}/dashboard/{project_id}/service" if project_id else None
    telemetry_logs_url = f"{base}/dashboard/{project_id}/logs" if project_id else None
    security_events_url = f"{base}/dashboard/{project_id}/security-events" if project_id else None
    security_detection_rules_url = (
        f"{base}/dashboard/{project_id}/security-events/detection-rules" if project_id else None)
    monitor_groups_url = f"{base}/dashboard/{project_id}/monitor-groups" if project_id else None
    # Same project-scoped-list pattern as the five above (PageMap.TRACES ->
    # RouteMap.ts confirmed, not guessed) - where cascading_incident.py's
    # synthetic OTel trace (Internet-Anbindung -> WLAN/Netzwerk (LAN)) shows
    # up as a real dependency edge in the Trace Service Map.
    traces_url = f"{base}/dashboard/{project_id}/traces" if project_id else None

    return {
        "oneuptimeBase": base,
        "statusPageId": summary.get("statusPageId"),
        "itServiceStatusPageId": summary.get("itServiceStatusPageId"),
        "leipzigStatusPageId": summary.get("leipzigStatusPageId"),
        "docuwareDiskIncidentRolesUrl": disk_incident.get("rolesUrl"),
        "onCallEscalationUrl": on_call_escalation_url,
        "onCallExecutionLogsUrl": on_call_execution_logs_url,
        "scheduledMaintenanceEventsUrl": scheduled_maintenance_events_url,
        "serviceCatalogUrl": service_catalog_url,
        "telemetryLogsUrl": telemetry_logs_url,
        "securityEventsUrl": security_events_url,
        "securityDetectionRulesUrl": security_detection_rules_url,
        "monitorGroupsUrl": monitor_groups_url,
        "tracesUrl": traces_url,
    }


OU_BASE = os.environ.get("OU_BASE", "http://localhost")
_ou_token = None  # cached across polls - see get_security_state() below


def _ou_login():
    global _ou_token
    payload = json.dumps({"data": {
        "email": {"_type": "Email", "value": "demo@example.com"},
        "password": {"_type": "HashedString", "value": "DemoDemo123!"},
    }}).encode()
    req = urllib.request.Request(f"{OU_BASE}/api/identity/login", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.load(resp)
    _ou_token = body.get("_miscData", {}).get("accessToken")
    return _ou_token


def get_monitor_state(monitor_name):
    """healthy/unhealthy/unknown for a scenario whose truth lives in
    OneUptime, not Prometheus (a Manual monitor + Incident, no metric
    backs it), so it needs the OneUptime API instead of prom_query().
    Shared by every scenario that just checks one monitor's operational
    status (security, Blueant, Jira attachments, ...) - the printer
    scenario is the one exception (checks a Scheduled Maintenance, not a
    monitor, see get_printer_state()). The login token is cached at
    module level and reused across polls (the panel polls /api/status
    every 5s) - OneUptime's login endpoint is rate-limited (10
    attempts/15min), so logging in on every poll would lock the demo
    account out within seconds."""
    global _ou_token
    try:
        if not _ou_token and not _ou_login():
            return "unknown"
        req = urllib.request.Request(
            f"{OU_BASE}/api/monitor/get-list", method="POST",
            data=json.dumps({
                "query": {}, "select": {"name": True, "currentMonitorStatus": {"isOperationalState": True}},
                "sort": {}, "skip": 0, "limit": 100,
            }).encode())
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {_ou_token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                _ou_token = None  # token expired/invalid - retry once with a fresh login
                if not _ou_login():
                    return "unknown"
                req.add_header("Authorization", f"Bearer {_ou_token}")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = json.load(resp)
            else:
                raise
        for m in body.get("data", []):
            if m.get("name") == monitor_name:
                op = (m.get("currentMonitorStatus") or {}).get("isOperationalState", True)
                return "healthy" if op else "unhealthy"
        return "unknown"
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError):
        return "unknown"


def get_printer_state():
    """healthy/unhealthy/unknown for the printer-maintenance-process
    scenario (#148) - like the security scenario, this one lives in
    OneUptime (a Scheduled Maintenance, no metric backs it): "unhealthy"
    means the live-triggered "Kurzfristige Wartung" entry is currently
    announced (not yet Completed), "healthy" means none is open right
    now. Deliberately not about the printer's own monitor status - that
    one is never touched by this scenario, see break-printer.sh."""
    global _ou_token
    try:
        if not _ou_token and not _ou_login():
            return "unknown"
        req = urllib.request.Request(
            f"{OU_BASE}/api/scheduled-maintenance/get-list", method="POST",
            data=json.dumps({
                "query": {}, "select": {
                    "title": True,
                    "currentScheduledMaintenanceState": {"isResolvedState": True},
                },
                "sort": {}, "skip": 0, "limit": 100,
            }).encode())
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {_ou_token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                _ou_token = None  # token expired/invalid - retry once with a fresh login
                if not _ou_login():
                    return "unknown"
                req.add_header("Authorization", f"Bearer {_ou_token}")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = json.load(resp)
            else:
                raise
        for m in body.get("data", []):
            if m.get("title") == "Kurzfristige Wartung – Drucker (Hauptgebäude)":
                resolved = (m.get("currentScheduledMaintenanceState") or {}).get("isResolvedState", True)
                return "unhealthy" if not resolved else "healthy"
        return "healthy"
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError):
        return "unknown"


def get_status():
    """healthy/unhealthy/unknown per scenario, read live from Prometheus -
    no separate state file invented here, Prometheus already is the
    stack's single source of truth (see docker-compose.yml header).
    Security, Blueant, Jira-attachments and printer are the exceptions
    (see get_monitor_state()/get_printer_state()) - they live in
    OneUptime, not Prometheus."""
    cert_days = prom_query('(probe_ssl_earliest_cert_expiry{demo_fixture="true"} - time()) / 86400')
    docuware_node2 = prom_query('docuware_mssql_cluster_node_up{node="db2"}')
    docuware_disk = prom_query('docuware_disk_usage_percent{volume="Dokumentenspeicher"}')
    cc_chemnitz = prom_query('cc_site_vpn_up{site="Chemnitz"}')
    leipzig_switch = prom_query('net_uplink_up{device="Access-Switch Vertrieb-2"}')
    cognigy_intent_success = prom_query('cc_cognigy_intent_success_rate_percent')
    shop_request_rate = prom_query('shop_request_rate_per_second')

    def state(value, healthy_fn):
        if value is None:
            return "unknown"
        return "healthy" if healthy_fn(value) else "unhealthy"

    return {
        "demo": state(cert_days, lambda v: v >= 3),
        "docuware": state(docuware_node2, lambda v: v >= 1),
        "docuware-disk": state(docuware_disk, lambda v: v < 90),
        "customer-care": state(cc_chemnitz, lambda v: v >= 1),
        "security": get_monitor_state("Anmeldung (SSO)"),
        "printer": get_printer_state(),
        "leipzig-network": state(leipzig_switch, lambda v: v >= 1),
        "cognigy": state(cognigy_intent_success, lambda v: v >= 90),
        "blueant": get_monitor_state("Blueant"),
        "jira-attachments": get_monitor_state("Anhänge & Dateien"),
        # Three monitors, one incident - polling just the root cause
        # (Internet-Anbindung) is enough to reflect the whole scenario:
        # it's the first to flip and the last to recover.
        "leipzig-cascade": get_monitor_state("Internet-Anbindung"),
        # Normal request rate tops out well under 100/s; the DDoS state
        # pushes it into the thousands (see webshop-metrics-exporter.py) -
        # 500 sits safely between the two.
        "ddos-shop": state(shop_request_rate, lambda v: v < 500),
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, root, rel_path):
        """Serves a file from `root`, rejecting any path that would escape
        it (e.g. `../../.env`) - `rel_path` comes straight from the URL."""
        rel_path = urllib.parse.unquote(rel_path) or "index.html"
        root = os.path.realpath(root)
        target = os.path.realpath(os.path.join(root, rel_path))
        if not (target == root or target.startswith(root + os.sep)) or not os.path.isfile(target):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(target)[1].lower()
        content_type = {".html": "text/html; charset=utf-8", ".css": "text/css",
                        ".js": "application/javascript", ".png": "image/png",
                        ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
        with open(target, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            html_path = os.path.join(HERE, "control-panel.html")
            with open(html_path, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self._json(get_status())
        elif self.path == "/api/links":
            self._json(get_links())
        elif self.path.startswith("/mockups/"):
            self._serve_static(os.path.join(DEMO_DIR, "mockups"), self.path[len("/mockups/"):])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/api/run":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "invalid JSON"}, status=400)
            return
        action = payload.get("action")
        entry = ACTIONS.get(action)
        if not entry:
            self._json({"ok": False, "error": f"unknown action '{action}'"}, status=400)
            return
        script, label = entry
        try:
            result = subprocess.run(
                ["sh", f"./{script}"], cwd=DEMO_DIR,
                capture_output=True, text=True, timeout=120,
            )
            self._json({
                "ok": result.returncode == 0,
                "label": label,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-2000:],
            })
        except subprocess.TimeoutExpired:
            self._json({"ok": False, "label": label, "error": "timed out after 120s"}, status=504)

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet - the page's own log panel shows results


if __name__ == "__main__":
    print(f"[control-panel] http://127.0.0.1:{PORT} (Prometheus: {PROM_URL})")
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
