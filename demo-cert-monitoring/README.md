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
       +         │                      │  + demo-broken-site (fest)
  demo-broken-   └──────────┬───────────┘
  site (fest,               │ scrape
  break-demo.sh)            ▼
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

`demo-broken-site` ist eine feste vierte Fixture (eigene nginx-Instanz mit
selbstsigniertem Zertifikat) neben euren echten `DEMO_TARGET_URLS` - sie
startet **gesund** und lässt sich live per `./break-demo.sh` /
`./fix-demo.sh` "kaputt machen" bzw. reparieren, siehe unten.

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
| demo-broken-site | https://localhost:8443 | Feste Demo-Fixture, siehe unten. Browser warnt vor dem selbstsignierten Zertifikat - das ist erwartet, einfach fortfahren |

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

1. OneUptime-Konto anlegen: entweder Cloud-Trial unter https://oneuptime.com,
   oder selbst gehostet über [`oneuptime-selfhosted/`](oneuptime-selfhosted/)
   in diesem Ordner (`./oneuptime-selfhosted/setup.sh --start` klont den
   offiziellen Release-Branch, generiert Secrets und startet die Instanz
   lokal). Der Self-Hosted-Stack ist mit ~15 Diensten (Postgres, Redis,
   ClickHouse, ...) deutlich schwerer als dieser Demo-Stack und deshalb
   bewusst **nicht** in `docker-compose.yml` eingebettet, sondern als
   eigenständiger Nachbar-Ordner.
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

## Test-Incident live durchspielen: "Zertifikat abgelaufen, IT arbeitet an Behebung"

`demo-broken-site` startet **gesund** (gültiges Zertifikat,
`DEMO_CERT_DAYS_REMAINING=90`). Mit `break-demo.sh` / `fix-demo.sh`
schaltet ihr live zwischen "gesund" und "Zertifikat abgelaufen" um und
könnt dabei zusehen, wie sich das durch den ganzen Stack zieht - genau
das, was App-Owner in Grafana und Endnutzer auf der Statuspage später
in echt erleben würden.

### 1. Vorfall auslösen

```bash
cd demo-cert-monitoring
./break-demo.sh
```

Das Skript regeneriert das Zertifikat von `demo-broken-site` als bereits
abgelaufen (`DEMO_CERT_DAYS_REMAINING=-2`) und startet den Container neu.
Danach live mitverfolgen:

| Wo | Was passiert | Zeitrahmen |
|---|---|---|
| Prometheus (`/alerts`) | `CertificateExpiringCritical` geht auf "Pending" → "Firing" für `demo-broken-site (absichtlich abgelaufenes Zertifikat)` | ~15s Scrape + 1 min `for:` |
| Grafana-Dashboard | Statustabelle + Zertifikats-Countdown-Panel zeigen die Zeile rot/negativ | ~30s Panel-Refresh |
| `docker compose logs -f oneuptime-sync` | Meldet `reachable but cert expires in -2 days -> treating as unhealthy`, hört auf zu pingen | nächster `SYNC_INTERVAL_SECONDS`-Zyklus (Default 60s) |
| OneUptime-Monitor / Statuspage | Monitor kippt auf "down", Status page zeigt den Service als beeinträchtigt | nach der konfigurierten "Not Received In Minutes"-Kulanzzeit |

Voraussetzung für die letzten beiden Zeilen: `ONEUPTIME_DEMO_HEARTBEAT_URL`
in `.env` gesetzt (siehe unten) - sonst bleibt es beim Prometheus-/
Grafana-Teil, was für eine reine App-Owner-Demo oft schon reicht.

### 2. (Optional) Vorfall in OneUptime sichtbar machen

Damit `demo-broken-site` überhaupt auf der Statuspage erscheint, braucht
es einen eigenen Monitor + Statuspage-Eintrag, analog zu den echten
Zielen oben:

1. In OneUptime einen weiteren **"Incoming Request"-Monitor** anlegen
   (z. B. `demo-broken-site`), zur Statuspage hinzufügen, "Not Received
   In Minutes" auf 3-5 min setzen.
2. Dessen Heartbeat-URL in `.env` eintragen:
   ```dotenv
   ONEUPTIME_DEMO_HEARTBEAT_URL=https://oneuptime.example.com/heartbeat/demo
   ```
3. `docker compose up -d` (nur `oneuptime-sync` neu startet).

Manche OneUptime-Projekte legen bei einem "down"-Monitor automatisch
einen Incident an (Projekteinstellung); falls nicht, oder wenn ihr die
Erzählung "IT ist dran" explizit zeigen wollt, den Incident manuell
ergänzen:

1. **OneUptime → Project → Incidents → Create Incident**
2. **Titel:** `TLS-Zertifikat für demo-broken-site abgelaufen`
3. **Beschreibung** (Markdown, erscheint auf der Statuspage):
   ```
   Das TLS-Zertifikat ist abgelaufen. Das IT-Team wurde benachrichtigt.
   ```
4. Mit dem `demo-broken-site`-Service/Monitor verknüpfen, Status
   `Identified`/`Investigating` setzen.
5. **Status-Update posten**, um "IT ist dran" sichtbar zu machen:
   ```
   Das IT-Team hat das abgelaufene Zertifikat identifiziert und
   erneuert es.
   ```

### 3. Vorfall auflösen

```bash
./fix-demo.sh
```

Regeneriert ein gesundes Zertifikat (`DEMO_CERT_DAYS_REMAINING=90`) und
startet `demo-broken-site` neu. Prometheus/Grafana erholen sich
automatisch auf dem nächsten Zyklus; `oneuptime-sync` pingt wieder;
den OneUptime-Incident ggf. manuell mit Status `Resolved` und einem
Abschluss-Update versehen (z. B. `Neues Zertifikat ist ausgerollt,
Störung behoben.`).

OneUptime bietet dafür auch eine REST-API (siehe
https://oneuptime.com/reference), falls ihr das Anlegen/Auflösen von
Incidents zusätzlich skripten wollt - die genauen Endpunkt-/Payload-
Details dort prüfen, da sie sich zwischen Versionen ändern können.

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
