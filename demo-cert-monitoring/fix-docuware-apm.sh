#!/bin/sh
# Sends a fast, healthy DocuWare example trace (same four-span shape as
# break-docuware-apm.sh, ~42ms total, every span STATUS_CODE_OK) into
# OneUptime - not a "revert" (nothing was changed in OneUptime's own
# status by break-docuware-apm.sh), just a second trace of contrasting
# shape so both are visible side by side in Traces.
#
# Requires OneUptime to be up and already seeded (./seed-oneuptime.sh).
# Run from demo-cert-monitoring/.
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

echo "==> Sending a healthy DocuWare example trace to OneUptime ..."
python3 scripts/docuware_apm_trace.py fix

echo ""
echo "==> Done. OneUptime's Traces view now has both the slow/error trace"
echo "    (from ./break-docuware-apm.sh) and this fast/healthy one for direct"
echo "    comparison."
