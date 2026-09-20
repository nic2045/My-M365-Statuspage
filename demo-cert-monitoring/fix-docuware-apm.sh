#!/bin/sh
# Sends a fast, healthy DocuWare example request (same four-step shape as
# break-docuware-apm.sh, ~42ms total, everything OK) into the same three
# back ends (Grafana Tempo, Grafana Loki, OneUptime) - not a "revert"
# (nothing was changed in any tool's own status by break-docuware-apm.sh),
# just a second, contrasting trace+logs so both states are visible side by
# side. Shares one fresh trace id across all three, same as
# break-docuware-apm.sh.
#
# All three targets are best-effort and independent - a failure in one must
# not stop the others from being attempted.
#
# Run from demo-cert-monitoring/.
set -eu

cd "$(dirname "$0")"

DOCUWARE_TRACE_ID_HEX=$(python3 -c "import os; print(os.urandom(16).hex())")
export DOCUWARE_TRACE_ID_HEX
echo "==> Trace-ID für diesen Durchlauf: $DOCUWARE_TRACE_ID_HEX (geteilt über Tempo/Loki/OneUptime)"
echo ""

TEMPO_OTLP_HTTP_PORT=$(grep -E '^TEMPO_OTLP_HTTP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
TEMPO_OTLP_HTTP_PORT="${TEMPO_OTLP_HTTP_PORT:-4318}"
export TEMPO_BASE="http://localhost:$TEMPO_OTLP_HTTP_PORT"

LOKI_HTTP_PORT=$(grep -E '^LOKI_HTTP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
LOKI_HTTP_PORT="${LOKI_HTTP_PORT:-3100}"
export LOKI_BASE="http://localhost:$LOKI_HTTP_PORT"

echo "==> Sending a healthy DocuWare trace to Grafana Tempo ..."
TEMPO_OK=1
python3 scripts/docuware_apm_tempo_trace.py fix || TEMPO_OK=0
if [ "$TEMPO_OK" = "0" ]; then
  echo "    (Tempo-Trace fehlgeschlagen - siehe Fehlermeldung oben.)"
fi

echo ""
echo "==> Sending the matching healthy log lines to Grafana Loki ..."
LOKI_OK=1
python3 scripts/docuware_apm_loki_logs.py fix || LOKI_OK=0
if [ "$LOKI_OK" = "0" ]; then
  echo "    (Loki-Logs fehlgeschlagen - siehe Fehlermeldung oben.)"
fi

ONEUPTIME_CONFIG="oneuptime-selfhosted/oneuptime/config.env"
ONEUPTIME_OK=1
if [ -f "$ONEUPTIME_CONFIG" ]; then
  OU_PORT=$(grep -E '^ONEUPTIME_HTTP_PORT=' "$ONEUPTIME_CONFIG" | tail -1 | cut -d= -f2-)
  OU_PORT="${OU_PORT:-80}"
  if [ "$OU_PORT" = "80" ]; then
    export OU_BASE="http://localhost"
  else
    export OU_BASE="http://localhost:$OU_PORT"
  fi
  echo ""
  echo "==> Sending the same trace + logs to OneUptime ..."
  python3 scripts/docuware_apm_trace.py fix || ONEUPTIME_OK=0
  if [ "$ONEUPTIME_OK" = "0" ]; then
    echo "    (OneUptime fehlgeschlagen - siehe Fehlermeldung oben.)"
  fi
else
  ONEUPTIME_OK=0
  echo ""
  echo "    (OneUptime übersprungen - $ONEUPTIME_CONFIG nicht gefunden.)"
fi

echo ""
if [ "$TEMPO_OK" = "0" ] && [ "$LOKI_OK" = "0" ] && [ "$ONEUPTIME_OK" = "0" ]; then
  echo "==> Alle drei Ziele fehlgeschlagen - siehe Fehlermeldungen oben."
  exit 1
fi
echo "==> Done. Both the slow/error version (from break-docuware-apm.sh) and this"
echo "    healthy version are now visible for direct comparison."
