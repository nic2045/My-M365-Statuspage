#!/bin/sh
# Sets up a self-hosted OneUptime instance next to (not merged into) the
# Prometheus/Grafana demo stack in ../docker-compose.yml.
#
# OneUptime is a full monitoring/status-page platform with its own
# multi-service docker-compose (Postgres, Redis, ClickHouse, several
# Node microservices) - too heavy to vendor into this repo, so this
# script clones OneUptime's own official release branch into ./oneuptime
# (git-ignored, never committed here) and prepares its config for a
# local demo run.
#
# Usage:
#   ./setup.sh          # clone + generate config.env, don't start
#   ./setup.sh --start  # also run `npm start` (falls back to `docker
#                          compose up -d` if npm is unavailable)
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLONE_DIR="$SCRIPT_DIR/oneuptime"
REPO_URL="https://github.com/OneUptime/oneuptime.git"

command -v docker >/dev/null 2>&1 || {
  echo "ERROR: docker is required. Install Docker (and Docker Compose) first." >&2
  exit 1
}
command -v git >/dev/null 2>&1 || {
  echo "ERROR: git is required to fetch OneUptime's own release branch." >&2
  exit 1
}

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    od -An -tx1 -N32 /dev/urandom | tr -d ' \n'
  fi
}

if [ -d "$CLONE_DIR/.git" ]; then
  echo "==> $CLONE_DIR already exists, skipping clone (delete it to re-clone)."
else
  echo "==> Cloning OneUptime (release branch, shallow) into $CLONE_DIR ..."
  git clone --depth 1 --single-branch --branch release "$REPO_URL" "$CLONE_DIR"
fi

cd "$CLONE_DIR"

if [ -f config.env ]; then
  echo "==> config.env already exists, leaving it untouched."
else
  echo "==> Generating config.env from config.example.env with randomized secrets ..."
  cp config.example.env config.env

  # Core secrets required for OneUptime to run at all. Optional
  # integrations (billing/Stripe, Slack app, Microsoft Teams app, GitHub
  # app, VAPID web-push, Let's Encrypt) are left as their example
  # placeholders/disabled - not needed for this demo (monitors + a
  # public status page).
  for key in \
    ONEUPTIME_SECRET \
    REGISTER_PROBE_KEY \
    DATABASE_PASSWORD \
    CLICKHOUSE_PASSWORD \
    REDIS_PASSWORD \
    ENCRYPTION_SECRET \
    GLOBAL_PROBE_1_KEY \
    GLOBAL_PROBE_2_KEY \
    ONEUPTIME_RUNNER_KEY \
    QUEUE_DASHBOARD_SECRET \
  ; do
    value=$(random_hex)
    if grep -q "^${key}=" config.env; then
      # Use | as sed delimiter since the generated hex never contains it.
      sed -i.bak "s|^${key}=.*|${key}=${value}|" config.env
    fi
  done
  rm -f config.env.bak

  echo "==> config.env written with randomized core secrets."
fi

echo ""
echo "==> Done. OneUptime will listen on http://\${HOST:-localhost} once started"
echo "    (default HOST=localhost, ONEUPTIME_HTTP_PORT=80 - edit $CLONE_DIR/config.env"
echo "    first if port 80 is taken or needs elevated privileges)."
echo ""
echo "    First boot pulls/builds several service images and can take a"
echo "    while. Resource guidance: check https://oneuptime.com/docs for"
echo "    current minimums - this is a full multi-service platform, not"
echo "    a lightweight single container."

if [ "${1:-}" = "--start" ]; then
  echo ""
  echo "==> Starting OneUptime ..."
  if command -v npm >/dev/null 2>&1; then
    npm start
  else
    export $(grep -v '^#' config.env | xargs)
    docker compose up --remove-orphans -d
  fi
else
  echo ""
  echo "==> Not starting automatically. To start now:"
  echo "      cd $CLONE_DIR && npm start"
  echo "    (or: cd $CLONE_DIR && export \$(grep -v '^#' config.env | xargs) && docker compose up --remove-orphans -d)"
fi
