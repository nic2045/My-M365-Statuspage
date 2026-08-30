#!/bin/sh
# Triggers the Jira-Anhänge demo scenario, live: OneUptime's "Anhänge &
# Dateien" monitor flips to Degraded and a real Incident ("Datei-Uploads in
# Jira schlagen fehl") appears on the IT-Services status page.
#
# Story: a narrow, sub-feature outage rather than "Jira is down" - only
# uploading new attachments fails, tickets/comments/search stay unaffected.
# Deliberately distinct from the "Benachrichtigungen" sub-service already
# used by refresh_demo.py's rotating-incident pool.
#
# Requires OneUptime to be up and already seeded (./seed-oneuptime.sh).
# Run from demo-cert-monitoring/. Reverse with ./fix-jira-attachments.sh.
set -eu

cd "$(dirname "$0")"

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
[ -f "$ONEUPTIME_CONFIG" ] || {
  echo "ERROR: $ONEUPTIME_CONFIG not found - OneUptime isn't set up yet." >&2
  echo "       Run: ./start-demo.sh --with-oneuptime && ./seed-oneuptime.sh" >&2
  exit 1
}

OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
OU_PORT="${OU_PORT:-80}"
if [ "$OU_PORT" = "80" ]; then
  OU_BASE="http://localhost"
else
  OU_BASE="http://localhost:$OU_PORT"
fi
export OU_BASE

echo "==> Triggering the Jira-Anhänge scenario ..."
python3 scripts/jira_attachments_incident.py break

echo ""
echo "==> Done. Within a few seconds the IT-Services status page shows:"
echo "      - \"Anhänge & Dateien\" degraded"
echo "      - New incident \"Datei-Uploads in Jira schlagen fehl\""
echo "    IT-Services: $OU_BASE (see .oneuptime-demo-summary for the exact URL)"
echo "    Recover with: ./fix-jira-attachments.sh"
