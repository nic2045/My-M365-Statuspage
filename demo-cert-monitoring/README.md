# Demo: Zertifikats- & Verfügbarkeits-Monitoring (Prometheus + Grafana + OneUptime)

> Eigenständiger Demo-Stack. Getrennt von der M365-Statuspage-App in diesem
> Repo (eigenes `docker-compose.yml`, eigenes `.env`, nicht Teil von CI oder
> des Haupt-Docker-Images). Zeigt exemplarisch, wie Zertifikats-Ablauf und
> Website-Verfügbarkeit für zwei Zielgruppen aufbereitet werden können:
> App-Owner (technisches Grafana-Dashboard) und Endnutzer (öffentliche
> OneUptime-Statuspage).

## Architektur

```
                 ┌─────────────────────┐
  DEMO_TARGET_   │   blackbox_exporter  │  HTTP(S)-Check + TLS-Cert-Ablauf
  URLS (2-3 URLs)│   (probe /probe)     │  je konfigurierter URL
                 └──────────┬───────────┘
                            │ scrape
                            ▼
                 ┌─────────────────────┐
                 │      Prometheus      │  einzige Quelle der Wahrheit
                 │  (Metriken + Alerts) │
                 └──────┬───────┬───────┘
                         │       │
             Prometheus  │       │  probe_success /
             Datasource  │       │  probe_ssl_earliest_cert_expiry
                         ▼       ▼
              ┌────────────┐  ┌──────────────────┐
              │  Grafana   │  │  oneuptime-sync   │ (optional)
              │ App-Owner  │  │  pingt Heartbeat- │
              │ Dashboard  │  │  URL bei "UP"     │
              └────────────┘  └─────────┬─────────┘
                                         ▼
                              ┌────────────────────┐
                              │      OneUptime      │
                              │ öffentliche Status- │
                              │ page für Endnutzer  │
                              └────────────────────┘
```

Prometheus probt selbst - OneUptime bekommt nur das Ergebnis gemeldet
(Heartbeat-Pattern), damit es nur eine Quelle der Wahrheit gibt und beide
Ansichten (Grafana intern, OneUptime öffentlich) konsistent bleiben.

## Setup

```bash
cd demo-cert-monitoring
cp .env.example .env
```

In `.env` die **2-3 Demo-URLs** setzen:

```dotenv
DEMO_TARGET_URLS=https://www.google.com,https://www.github.com,https://www.wikipedia.org
```

Stack starten:

```bash
docker compose up -d
```

## Zugriff

| Dienst | URL | Hinweis |
|---|---|---|
| Grafana (App-Owner) | http://localhost:3000 | Login `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` aus `.env`; Dashboard **"Website & Zertifikats-Monitoring (App-Owner)"** ist bereits provisioniert |
| Prometheus | http://localhost:9090 | Rohdaten, Targets (`/targets`), Alert-Regeln (`/alerts`) |
| blackbox_exporter | http://localhost:9115 | Debug: `/probe?target=https://...&module=http_2xx` |

Das Grafana-Dashboard zeigt: Anzahl erreichbarer Websites, kürzeste
verbleibende Zertifikatslaufzeit, eine Statustabelle je URL sowie
Zeitreihen für Antwortzeit und Zertifikats-Countdown (Ampel-Schwellen bei
30/14/3 Tagen).

Zwei Alert-Regeln (`WebsiteDown`, `CertificateExpiringSoon` /
`-Critical`) sind in Prometheus hinterlegt und in `/alerts` sichtbar - für
die Demo ist **kein Alertmanager** verkabelt (keine E-Mail/Slack-Zustellung),
das wäre der nächste Ausbauschritt für einen Produktiveinsatz.

## OneUptime-Anbindung (öffentliche Statuspage)

Der `oneuptime-sync`-Dienst ist optional und macht bei leerem
`ONEUPTIME_HEARTBEAT_URLS` nichts (Prometheus + Grafana laufen trotzdem
vollständig). Für die volle Demo:

1. OneUptime-Konto anlegen (Cloud-Trial unter https://oneuptime.com oder
   selbst gehostet - der offizielle Self-Hosted-Stack ist mit ~15
   Diensten (Postgres, Redis, ClickHouse, ...) deutlich schwerer als dieser
   Demo-Stack und deshalb hier bewusst **nicht** eingebettet).
2. Pro Ziel-URL einen Monitor vom Typ **"Incoming Request" / "Heartbeat"**
   anlegen. OneUptime generiert dafür eine eindeutige URL.
3. Diese Monitore zu einer öffentlichen **Status Page** in OneUptime
   hinzufügen.
4. Die generierten Heartbeat-URLs in `.env` eintragen - **Reihenfolge muss
   zu `DEMO_TARGET_URLS` passen**:

   ```dotenv
   DEMO_TARGET_URLS=https://a.example.com,https://b.example.com
   ONEUPTIME_HEARTBEAT_URLS=https://oneuptime.example.com/heartbeat/xxx,https://oneuptime.example.com/heartbeat/yyy
   ```

5. Stack neu starten (`docker compose up -d`). Solange Prometheus für eine
   URL `probe_success == 1` misst, pingt `oneuptime-sync` die zugehörige
   Heartbeat-URL alle `SYNC_INTERVAL_SECONDS` (Default 60s). Bleibt der
   Ping aus, markiert OneUptime den Monitor nach seiner eigenen
   Kulanzzeit als "down" - dort konfigurierbar.

## Aufräumen

```bash
docker compose down -v
```

## Warum getrennt vom Haupt-Repo-Code?

Dieser Ordner ist bewusst isoliert (eigenes Compose-File, eigenes `.env`,
kein Bezug zu `app/`, `Dockerfile`, `pyproject.toml` oder den
GitHub-Actions-Workflows der M365-Statuspage). Er demonstriert einen
anderen Anwendungsfall (generisches Website-/Zertifikats-Monitoring) mit
einem anderen Technologie-Stack (Prometheus/Grafana/OneUptime statt
FastAPI + Microsoft Graph API) und soll die Haupt-App nicht aufblähen oder
deren CI/Build beeinflussen.
