#!/bin/sh
# Sends the slow/error DocuWare example request (docuware-frontend ->
# docuware-api-gateway -> docuware-service -> docuware-db, 2.2s total, DB
# call times out) into THREE back ends at once - the same DocuWare story
# told by mockups/gap-monitoring-today-tomorrow.html, but as real telemetry
# instead of a static screenshot:
#   - Grafana Tempo: the trace (waterfall + search in Grafana Explore)
#   - Grafana Loki: matching log lines, one per service
#   - OneUptime: the same trace AND the same log lines (basic ingestion,
#     for comparison against the dedicated Tempo/Loki stack)
#
# All three share one trace id (DOCUWARE_TRACE_ID_HEX, generated once
# below) embedded as "trace_id=<hex>" in every Loki/OneUptime log line -
# that's what makes Grafana's log<->trace correlation work (see
# grafana/provisioning/datasources/loki.yml's derivedFields and tempo.yml's
# tracesToLogsV2): open the trace in Tempo, jump straight to its logs, or
# the other way round.
#
# All three targets are best-effort and independent: a failure in one
# (Tempo/Loki not pulled/started yet, OneUptime not seeded) is reported but
# does NOT stop the script from still attempting the others - same
# principle as the existing cascade trace in cascading_incident.py. Without
# this, `set -eu` would abort at the first failing target and the rest
# would silently never even be attempted.
#
# None of the three touch a monitor or incident - purely adds telemetry, so
# there is nothing to "break" in any tool's own status. Run
# ./fix-docuware-apm.sh afterwards to send a fast, healthy version of the
# same request for contrast.
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

echo "==> Sending the slow/error DocuWare trace to Grafana Tempo ..."
TEMPO_OK=1
python3 scripts/docuware_apm_tempo_trace.py break || TEMPO_OK=0
if [ "$TEMPO_OK" = "0" ]; then
  echo "    (Tempo-Trace fehlgeschlagen - siehe Fehlermeldung oben. Läuft der"
  echo "     Tempo-Container? \`docker compose ps tempo\` / \`docker compose logs tempo\`.)"
fi

echo ""
echo "==> Sending the matching log lines to Grafana Loki ..."
LOKI_OK=1
python3 scripts/docuware_apm_loki_logs.py break || LOKI_OK=0
if [ "$LOKI_OK" = "0" ]; then
  echo "    (Loki-Logs fehlgeschlagen - siehe Fehlermeldung oben. Läuft der"
  echo "     Loki-Container? \`docker compose ps loki\` / \`docker compose logs loki\`.)"
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
  python3 scripts/docuware_apm_trace.py break || ONEUPTIME_OK=0
  if [ "$ONEUPTIME_OK" = "0" ]; then
    echo "    (OneUptime fehlgeschlagen - siehe Fehlermeldung oben.)"
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
if [ "$LOKI_OK" = "1" ]; then
  echo "    Grafana Loki:    Explore -> Datenquelle 'Loki' -> LogQL"
  echo "                     '{service_name=~\"docuware.*\"}' - Log-Zeile anklicken"
  echo "                     springt direkt zum verlinkten Tempo-Trace"
fi
if [ -f "$ONEUPTIME_CONFIG" ] && [ "$ONEUPTIME_OK" = "1" ]; then
  echo "    OneUptime:       Traces & Telemetry -> Logs - $OU_BASE"
fi
if [ "$TEMPO_OK" = "0" ] && [ "$LOKI_OK" = "0" ] && [ "$ONEUPTIME_OK" = "0" ]; then
  echo "    Alle drei Ziele fehlgeschlagen - siehe Fehlermeldungen oben."
  exit 1
fi
echo "    Send a healthy contrast version with: ./fix-docuware-apm.sh"
