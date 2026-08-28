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

## Test-Incident: "Zertifikat abgelaufen, IT arbeitet an Behebung" (Demo)

Für eine Demo der Endnutzer-Statuspage braucht ihr nicht zwingend ein
echtes abgelaufenes Zertifikat - ein manuell angelegter Incident reicht
und zeigt die volle Optik (Titel, Beschreibung, Status-Update-Verlauf),
die App-Owner später live pflegen würden:

1. **OneUptime → Project → Incidents → Create Incident**
2. **Titel:** z. B. `TLS-Zertifikat für www.example.com abgelaufen`
3. **Beschreibung** (Markdown, erscheint auf der öffentlichen Statuspage):
   ```
   Das TLS-Zertifikat für https://www.example.com ist am 27.08.2026
   abgelaufen. Das IT-Team wurde benachrichtigt.
   ```
4. **Betroffene Ressource verknüpfen:** denselben Service auswählen, der
   in Schritt 3-4 der OneUptime-Anbindung oben mit dem Incoming-Request-
   Monitor verbunden wurde - nur so erscheint der Incident auf der
   Statuspage neben dem richtigen Service.
5. **Incident-Status setzen:** `Identified` oder `Investigating` (Namen
   hängen vom Projekt ab) - das markiert den Service auf der Statuspage
   als beeinträchtigt, ohne ihn komplett auf "down" zu setzen.
6. **Status-Update posten** (Incident → Post Update), um "IT ist dran"
   sichtbar zu machen:
   ```
   Das IT-Team hat das abgelaufene Zertifikat identifiziert und
   erneuert es. Wir aktualisieren diesen Incident, sobald das neue
   Zertifikat ausgerollt ist.
   ```
7. Zum Abschluss der Demo: ein weiteres Update mit Status `Resolved` und
   z. B. `Neues Zertifikat ist ausgerollt, Störung behoben.` posten.

Das Ergebnis: Endnutzer sehen auf der öffentlichen Statuspage einen
Service mit gelbem/orangem Status, den Incident-Titel, die laufenden
Updates - und am Ende die Auflösung, chronologisch nachvollziehbar.

OneUptime bietet dafür auch eine REST-API (siehe
https://oneuptime.com/reference), falls ihr das Anlegen/Auflösen von
Test-Incidents später skripten wollt - die genauen Endpunkt-/Payload-
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
