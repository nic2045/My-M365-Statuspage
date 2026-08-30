#!/bin/sh
# Reverses break-jira-attachments.sh: posts a resolution update to the
# incident's public timeline, sets it to Resolved, and puts "Anhänge &
# Dateien" back to Operational.
set -eu

cd "$(dirname "$0")"

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
[ -f "$ONEUPTIME_CONFIG" ] || {
  echo "ERROR: $ONEUPTIME_CONFIG not found - OneUptime isn't set up yet." >&2
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

echo "==> Resolving the Jira-Anhänge scenario ..."
python3 scripts/jira_attachments_incident.py fix

echo ""
echo "==> Done. The incident is Resolved, \"Anhänge & Dateien\" is Operational again."
