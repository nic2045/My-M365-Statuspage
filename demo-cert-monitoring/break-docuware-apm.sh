#!/bin/sh
# Sends the slow/error DocuWare example trace (docuware-frontend ->
# docuware-api-gateway -> docuware-service -> docuware-db, 2.2s total, DB
# span times out) into BOTH Grafana Tempo and OneUptime - the same
# DocuWare story told by mockups/gap-monitoring-today-tomorrow.html, but
# as real OTLP traces instead of a static screenshot. One click, two
# back ends, direct side-by-side comparison: what a dedicated APM/tracing
# tool (Tempo, trace waterfall + search in Grafana) shows for this trace
# vs. what OneUptime's own basic OTLP ingestion shows for the identical
# spans.
#
# Both halves are best-effort and independent: a failure in one (Tempo
# not pulled/started yet, OneUptime not seeded) is reported but does NOT
# stop the script from still attempting the other - same principle as the
# existing cascade trace in cascading_incident.py. Without this, `set -eu`
# would abort at the first failing half and the second would silently
# never even be attempted, which is exactly what happened before this was
# fixed (Tempo returning an error aborted the whole script, so "no traces
# in OneUptime" was actually just it never being tried).
#
# Neither half touches a monitor or incident - purely adds telemetry, so
# there is nothing to "break" in either tool's own status. Run
# ./fix-docuware-apm.sh afterwards to send a fast, healthy trace of the
# same shape for contrast.
#
# Run from demo-cert-monitoring/.
set -eu

cd "$(dirname "$0")"

TEMPO_OTLP_HTTP_PORT=$(grep -E '^TEMPO_OTLP_HTTP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
TEMPO_OTLP_HTTP_PORT="${TEMPO_OTLP_HTTP_PORT:-4318}"
export TEMPO_BASE="http://localhost:$TEMPO_OTLP_HTTP_PORT"

echo "==> Sending the slow/error DocuWare example trace to Grafana Tempo ..."
TEMPO_OK=1
python3 scripts/docuware_apm_tempo_trace.py break || TEMPO_OK=0
if [ "$TEMPO_OK" = "0" ]; then
  echo "    (Tempo-Trace fehlgeschlagen - siehe Fehlermeldung oben. Läuft der"
  echo "     Tempo-Container? \`docker compose ps tempo\` / \`docker compose logs tempo\`.)"
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
  echo "==> Sending the same trace to OneUptime ..."
  python3 scripts/docuware_apm_trace.py break || ONEUPTIME_OK=0
  if [ "$ONEUPTIME_OK" = "0" ]; then
    echo "    (OneUptime-Trace fehlgeschlagen - siehe Fehlermeldung oben.)"
  fi
else
  ONEUPTIME_OK=0
  echo ""
  echo "    (OneUptime übersprungen - $ONEUPTIME_CONFIG nicht gefunden."
  echo "     Für den Vergleich: ./start-demo.sh --with-oneuptime && ./seed-oneuptime.sh)"
fi

echo ""
echo "==> Done."
if [ "$TEMPO_OK" = "1" ]; then
  echo "    Grafana Tempo:   Explore -> Datenquelle 'Tempo' -> TraceQL"
  echo "                     '{resource.service.name=\"docuware-frontend\"}'"
  echo "                     (Grafana: http://localhost:\${GRAFANA_PORT:-3000})"
fi
if [ -f "$ONEUPTIME_CONFIG" ] && [ "$ONEUPTIME_OK" = "1" ]; then
  echo "    OneUptime:       Traces (bzw. Traces -> Service Map) - $OU_BASE"
fi
if [ "$TEMPO_OK" = "0" ] && [ "$ONEUPTIME_OK" = "0" ]; then
  echo "    Beide Ziele fehlgeschlagen - siehe Fehlermeldungen oben."
  exit 1
fi
echo "    Send a healthy contrast trace with: ./fix-docuware-apm.sh"
