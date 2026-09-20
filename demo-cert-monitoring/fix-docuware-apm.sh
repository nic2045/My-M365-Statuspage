#!/bin/sh
# Sends a fast, healthy DocuWare example trace (same four-span shape as
# break-docuware-apm.sh, ~42ms total, every span STATUS_CODE_OK) into both
# Grafana Tempo and (if set up) OneUptime - not a "revert" (nothing was
# changed in either tool's own status by break-docuware-apm.sh), just a
# second trace of contrasting shape so both are visible side by side.
#
# Run from demo-cert-monitoring/.
set -eu

cd "$(dirname "$0")"

TEMPO_OTLP_HTTP_PORT=$(grep -E '^TEMPO_OTLP_HTTP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
TEMPO_OTLP_HTTP_PORT="${TEMPO_OTLP_HTTP_PORT:-4318}"
export TEMPO_BASE="http://localhost:$TEMPO_OTLP_HTTP_PORT"

echo "==> Sending a healthy DocuWare example trace to Grafana Tempo ..."
python3 scripts/docuware_apm_tempo_trace.py fix

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
if [ -f "$ONEUPTIME_CONFIG" ]; then
  OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
  OU_PORT="${OU_PORT:-80}"
  if [ "$OU_PORT" = "80" ]; then
    export OU_BASE="http://localhost"
  else
    export OU_BASE="http://localhost:$OU_PORT"
  fi
  echo ""
  echo "==> Sending the same trace to OneUptime ..."
  python3 scripts/docuware_apm_trace.py fix
else
  echo ""
  echo "    (OneUptime übersprungen - $ONEUPTIME_CONFIG nicht gefunden.)"
fi

echo ""
echo "==> Done. Both traces (slow/error from break-docuware-apm.sh, fast/healthy"
echo "    from here) are now visible for direct comparison."
