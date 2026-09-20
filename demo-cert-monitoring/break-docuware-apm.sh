#!/bin/sh
# Sends the slow/error DocuWare example trace (docuware-frontend ->
# docuware-api-gateway -> docuware-service -> docuware-db, 2.2s total, DB
# span times out) into OneUptime - the same DocuWare story told by
# mockups/gap-monitoring-today-tomorrow.html, but as a real OTLP trace
# instead of a static screenshot. Purpose: side-by-side comparison of
# "what does OneUptime already show from raw trace ingestion" against
# "what a dedicated APM tool would show" (see README, Grafana Tempo
# integration).
#
# Doesn't touch any monitor or incident - purely adds telemetry, so there
# is nothing to "break" in OneUptime's own status. Run ./fix-docuware-apm.sh
# afterwards to send a fast, healthy trace of the same shape for contrast.
#
# Requires OneUptime to be up and already seeded (./seed-oneuptime.sh).
# Run from demo-cert-monitoring/.
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

echo "==> Sending the slow/error DocuWare example trace to OneUptime ..."
python3 scripts/docuware_apm_trace.py break

echo ""
echo "==> Done. In OneUptime: Traces (or Traces -> Service Map) shows the"
echo "    docuware-frontend -> ... -> docuware-db chain with the DB span"
echo "    in error - the same story as the gap-monitoring mockup, as real"
echo "    telemetry. OneUptime: $OU_BASE"
echo "    Send a healthy contrast trace with: ./fix-docuware-apm.sh"
