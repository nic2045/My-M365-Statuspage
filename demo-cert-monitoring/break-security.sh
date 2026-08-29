#!/bin/sh
# Triggers the security-incident demo scenario, live: OneUptime's
# "Anmeldung (SSO)" monitor flips to Degraded and a real Incident
# ("Ungewöhnliche Anmeldeaktivität wird untersucht" - suspicious login
# activity under investigation) appears on the IT-Services status page,
# written in plain, non-technical language.
#
# Complements the three already-resolved historical security incidents
# seed-oneuptime.sh creates (see README) - this one is live-triggerable
# instead of static, so the "detected -> investigated -> resolved" flow
# can be shown end-to-end. Once fixed (./fix-security.sh), it becomes a
# fourth entry in that same history.
#
# Requires OneUptime to be up and already seeded (./seed-oneuptime.sh).
# Run from demo-cert-monitoring/. Reverse with ./fix-security.sh.
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

echo "==> Triggering the security-incident scenario ..."
python3 scripts/security_incident.py break

echo ""
echo "==> Done. Within a few seconds the IT-Services status page shows:"
echo "      - \"Anmeldung (SSO)\" degraded"
echo "      - New incident \"Ungewöhnliche Anmeldeaktivität wird untersucht\""
echo "    IT-Services: $OU_BASE (see .oneuptime-demo-summary for the exact URL)"
echo "    Recover with: ./fix-security.sh"
