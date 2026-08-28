# Self-hosted OneUptime (public status page for end users)

> Separate stack, deliberately **not** merged into `../docker-compose.yml`.
> OneUptime is a full monitoring/observability platform with its own
> multi-service compose (Postgres, Redis, ClickHouse, several Node
> microservices) - vendoring that into this lightweight demo repo would
> both bloat it and go stale the moment OneUptime changes its own setup.
> Instead, `setup.sh` clones OneUptime's official release branch at run
> time and prepares it for a local demo run.

## Prerequisites

- Docker + Docker Compose
- `git`
- Meaningfully more resources than the Prometheus/Grafana stack next to
  it: OneUptime is a full platform (Postgres, Redis, ClickHouse, multiple
  services). Check [oneuptime.com/docs](https://oneuptime.com/docs) for
  current minimums before running this on anything small.

## 1. Set up and start

```bash
cd demo-cert-monitoring/oneuptime-selfhosted
./setup.sh          # clones OneUptime (release branch) into ./oneuptime,
                     # generates ./oneuptime/config.env with randomized
                     # core secrets, does not start anything yet
./setup.sh --start   # same, then starts OneUptime (npm start, or
                     # docker compose up -d as a fallback if npm is
                     # missing)
```

First boot pulls/builds several service images and can take a while.
Once up, OneUptime is reachable at `http://localhost` (default
`HOST=localhost`, `ONEUPTIME_HTTP_PORT=80` in
`oneuptime/config.env` - edit those first if port 80 is taken or needs
elevated privileges on your machine).

`./oneuptime/` and its `config.env` (real generated secrets) are
git-ignored - never committed to this repo.

## 2. Create your admin account & project

Open the instance in a browser, sign up (first account becomes admin on
a fresh self-hosted instance), and create a project.

## 3. Create one "Incoming Request" (heartbeat) monitor per demo URL

**Project Settings → Monitors → Create Monitor**, type **Incoming
Request**, one per URL in `../DEMO_TARGET_URLS`. Each monitor gives you a
unique ingestion URL.

Set the monitor's **"Not Received In Minutes"** criteria to **3-5
minutes** - our `oneuptime-sync` sidecar pings every
`SYNC_INTERVAL_SECONDS` (default 60s / 1 minute), so this gives enough
slack to avoid false alarms from a single delayed cycle.

## 4. Create the public status page

**Project Settings → Status Pages → Create Status Page**, add each
service under **Resources**, and link it to its Incoming Request
monitor. Set the page to public and note its URL - that's what end
users see.

## 5. Wire it back into the demo stack

In `../.env` (the Prometheus/Grafana/OneUptime-sync stack's own env
file), fill in the heartbeat URLs from step 3, **in the same order** as
`DEMO_TARGET_URLS`:

```dotenv
DEMO_TARGET_URLS=https://a.example.com,https://b.example.com,https://c.example.com
ONEUPTIME_HEARTBEAT_URLS=https://.../heartbeat/monitor-a,https://.../heartbeat/monitor-b,https://.../heartbeat/monitor-c
```

Then, back in `../`:

```bash
cd ..
docker compose up -d
docker compose logs -f oneuptime-sync
```

`oneuptime-sync` reads `probe_success` from Prometheus for each target
and pings the matching heartbeat URL whenever it's up; if a target goes
down, the ping stops and OneUptime marks the monitor (and the public
status page) down after the "Not Received In Minutes" grace period.

## Tearing down

```bash
cd oneuptime && docker compose down -v   # or: npm stop, per OneUptime's own docs
```

`rm -rf oneuptime/` removes the cloned platform entirely (config/secrets
included) if you want a clean slate.
