#!/bin/sh
# Picks up local code edits without a full ./start-demo.sh cycle.
#
# What already reloads on its own, no script needed:
#   - Grafana dashboards (grafana/dashboards/*.json): the file provisioner
#     re-scans every 30s (updateIntervalSeconds in
#     grafana/provisioning/dashboards/) - just save and wait.
#   - mockups/*.html and scripts/control-panel.html: served fresh from
#     disk on every request (static files) - just save and reload the
#     browser tab.
#
# What does NOT reload on its own, and this script restarts:
#   - scripts/*-metrics-exporter.py / leipzig-network-exporter.py: each
#     runs inside a long-lived container from a bind-mounted file: Python
#     only reads it once at container start, so an edit needs the
#     container recreated.
#   - scripts/control_panel_server.py: a plain host process (not in
#     Docker), same story - Python doesn't hot-reload its own source.
#
# Usage: ./reload-demo.sh
set -eu

cd "$(dirname "$0")"

echo "==> Restarting metrics exporters (picks up script edits) ..."
docker compose up -d --force-recreate \
  docuware-metrics-exporter \
  customer-care-metrics-exporter \
  leipzig-network-metrics-exporter \
  2>&1 | grep -v "^$" || true

echo ""
echo "==> Restarting control panel (picks up control_panel_server.py edits) ..."
if command -v lsof >/dev/null 2>&1; then
  PID=$(lsof -nP -iTCP:"${CONTROL_PANEL_PORT:-7100}" -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    sleep 1
  fi
fi
nohup ./control-panel.sh >/tmp/control-panel.log 2>&1 &
disown 2>/dev/null || true
sleep 1

echo ""
echo "==> Done."
echo "    Kontrollzentrum: http://localhost:${CONTROL_PANEL_PORT:-7100} (im Hintergrund neu gestartet)"
echo "    Grafana-Dashboard-Änderungen: automatisch innerhalb von ~30s sichtbar, kein Neustart nötig."
echo "    Mockup-/control-panel.html-Änderungen: Browser-Tab neu laden reicht."
echo "    Für Seed-/Statuspage-Änderungen weiterhin: ./seed-oneuptime.sh"
