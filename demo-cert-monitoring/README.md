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

### Schnellstart (empfohlen)

`./start-demo.sh` macht den kompletten Ablauf in einem Rutsch: prüft
Docker und die Host-Ports, legt `.env` beim ersten Lauf aus
`.env.example` an, startet den Stack und **wartet, bis Prometheus und
Grafana wirklich antworten und die ersten Probe-Ergebnisse da sind** -
damit eine Demo nie gegen ein noch bootendes Grafana startet. Am Ende
gibt es alle URLs aus.

```bash
cd demo-cert-monitoring
./start-demo.sh                    # nur der Kern-Stack (schnell)
./start-demo.sh --break            # Kern-Stack, danach direkt den Zertifikats-Vorfall auslösen
./start-demo.sh --with-oneuptime   # zusätzlich das selbstgehostete OneUptime (dauert lange, s.u.)
```

Herunterfahren mit `./stop-demo.sh` - stoppt automatisch **auch OneUptime**,
falls eingerichtet (eigenes Compose-Projekt, das ein reines `docker compose
down` in diesem Ordner nicht sieht - sonst laufen Postgres/ClickHouse/Redis/...
unbemerkt weiter). Volumes bleiben dabei erhalten. `--no-oneuptime` lässt
OneUptime laufen, `--purge` löscht zusätzlich alle Volumes (irreversibel).

### Manuell

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
vollständig).

### Automatisch (empfohlen)

`./start-demo.sh --with-oneuptime` startet OneUptime **und legt die
komplette Demo-Einrichtung direkt an** - über `seed-oneuptime.sh`:

- Demo-Account `demo@example.com` / `DemoDemo123!` (der erste Account
  wird automatisch Master Admin; eine E-Mail-Verifizierung entfällt, weil
  bei `BILLING_ENABLED=false` direkt als verifiziert angelegt wird - im
  Stack läuft ohnehin kein Mailserver)
- Projekt **Zertifikats-Monitoring Demo**

**Drei öffentliche Statusseiten, drei unterschiedliche Fälle** (bewusst
getrennt statt eine Seite mit allem):

1. **Statusseite Zertifikats-Monitoring** - reiner Showcase für
   Website-/Zertifikats-Überwachung: je ein **"Incoming Request"**-Monitor
   pro `DEMO_TARGET_URLS`-Eintrag plus **Demo-Website
   (Zertifikats-Fixture)**, Kriterium "kein Heartbeat seit 5 Minuten →
   Offline + Incident". Zeigt nur die rohen Ziel-URLs, keine
   Mitarbeiter-Dienste - "wie kann man Zertifikats-Monitoring darstellen".
   Ein aus `DEMO_TARGET_URLS` entfernter Eintrag wird beim nächsten Lauf
   automatisch samt Monitor von der Seite entfernt statt verwaist stehen
   zu bleiben.
2. **Statusseite IT-Services (Mitarbeiter)** - IT-Service-Sicht für
   Mitarbeitende: "Kann ich gerade arbeiten?" Enthält:
   - **Jira- und Outlook-„Health"** (Gruppen "Aufgabenverwaltung (Jira)" /
     "E-Mail & Kalender (Outlook)"): nutzerfreundliche Teilstatus ohne
     Technik-Begriffe ("Anmeldung & Ticket-Suche" statt "Tomcat", "E-Mail
     senden/empfangen" statt "DB")
   - **Weitere interne Dienste** (VPN, Finanzapplikationen,
     Projektmanagement-Tools, Blueant) mit `displayDescription` als
     Performance-Einordnung in Alltagssprache ("Antwortzeit: normal")
   - **DocuWare** (Dokumentenmanagement) - siehe eigener Abschnitt unten
   - Wartungen "Patchday Server Gruppe 3" (Status "Ongoing", Blueant
     betroffen und auf "Degraded" gesetzt), "Wartungsfenster VPN-Gateway"
     (Status "Scheduled"), **abgeschlossen:** "Patchday Server Gruppe 1 & 2"
     (Status "Completed" - erzählerischer Vorgänger von Gruppe 3)
   - Ankündigung "Geplantes Firewall-Upgrade (Barracuda)"

   Alle Dienste sind feste `Manual`-Monitore ohne Sensor, starten
   automatisch grün und werden nur gezielt (z.B. via Wartung/Incident) auf
   einen anderen Status gesetzt.
3. **Statusseite Standort Leipzig** - standortbezogene Facility-IT:
   Internet, Netzwerk, WLAN, Drucker - inkl. geplanter Druckerwartung
   (nutzerorientiert: was/wann/Alternative/Kontakt) und **abgeschlossen:**
   "Wartung Netzwerk-Switches (Rechenzentrum Leipzig)".

**Alle Termine werden bei jedem Lauf neu relativ zu "heute" berechnet**
(Patchday 3 läuft immer gerade jetzt, abgeschlossene Wartungen liegen
immer 6-10 Tage in der Vergangenheit, die Druckerwartung immer am
kommenden Freitag, das Firewall-Fenster immer Mi–Fr der nächsten Woche),
damit die Demo auch Wochen später noch aktuell aussieht.

Auch die Incident-Meldung selbst ist deutsch: kippt ein Monitor, legt
OneUptime automatisch einen Incident **"&lt;Name&gt; ist offline"** an, mit dem
Text "Seit 5 Minuten ist kein Heartbeat für &lt;Name&gt; eingegangen. Die
Überwachung meldet das Ziel als nicht erreichbar oder das TLS-Zertifikat
als abgelaufen. Die IT arbeitet an der Behebung." Der Incident erscheint
damit auch auf der öffentlichen Statusseite und wird nach der Erholung
automatisch auf "Resolved" gesetzt. Die erzeugten Heartbeat-URLs werden
nach `.env` zurückgeschrieben und `oneuptime-sync` neu gestartet.

**Branding statt Icons pro Zeile:** Emoji im Anzeigenamen wirkten zu
verspielt. OneUptime hat kein Icon-Feld pro Ressource/Gruppe, aber ein
`logoFileId` pro Statusseite (`headerHTML`/`customCSS`/`footerHTML`
funktionieren dagegen nur mit verifizierter Custom-Domain - auf der
lokalen Demo-URL unsichtbar, deshalb ungenutzt). Zertifikate und Leipzig
bekommen je ein schlichtes SVG-Logo (hochgeladen als `File`,
`isPublic: true`) - blau/Schild bzw. orange/Pin. Die IT-Services-Seite
zeigt stattdessen das echte DocuWare-Logo (`assets/docuware-logo.png`,
© DocuWare Corporation, [CC BY-SA
4.0](https://de.wikipedia.org/wiki/Datei:Docuware_logo_2018_bg_white_0.png)
via Wikimedia Commons) - DocuWare ist die zentrale Anwendung auf dieser
Seite.

> **Stabile URLs?** Geprüft: echtes CNAME-Custom-Domain-Routing
> (`StatusPageDomain`) verifiziert beim Setzen von `isVerified` aktiv per
> DNS-TXT-Abfrage gegen echte Nameserver - für eine rein lokale Demo ohne
> echte Domain (auch `*.localhost`) nicht erfüllbar, live getestet und
> verworfen. Nicht nötig ist es ohnehin: `seed-oneuptime.sh` findet
> Seiten/Monitore über ihren Namen wieder statt sie neu anzulegen, die
> `/status-page/<id>`-URLs bleiben über Neustarts hinweg stabil (in dieser
> Session über zahlreiche Läufe hinweg bestätigt).

**Admin-/Infrastruktur- und AI-Observability-Beispiel** (nicht auf einer
öffentlichen Statusseite - `MonitorGroup`/`MonitorGroupResource`
organisieren Monitore nur auf OneUptimes eigenem internen Dashboard):
Gruppe "Infrastruktur-Monitoring (Admin)" (OpenShift-Cluster,
MSSQL-Datenbanken, VMware-Umgebung, Server, Storage,
Netzwerk-Backbone) und Gruppe "AI / LLM Observability
(llm.pyur.com)" (Modell-Verfügbarkeit, Latenz & Durchsatz,
GPU-Auslastung, Guardrails & Fehlerquote, Kosten & Nutzung) - beide rein
statisch/beispielhaft, `Manual`-Monitore mit beschreibendem Text.

Das Skript ist idempotent und konvergent - ein erneuter Lauf verwendet
vorhandenen Account, Projekt, Monitore und Statuspage weiter (statt
Duplikate anzulegen) und zieht sie zugleich auf die aktuellen Texte und
Einstellungen nach. Objekte aus älteren Läufen mit englischen Namen
werden dabei umbenannt, nicht doppelt angelegt. Separat aufrufbar mit `./seed-oneuptime.sh` (Optionen:
`--email`, `--password`, `--project`, `--heartbeat-minutes`).
Überspringen mit `./start-demo.sh --with-oneuptime --no-seed`.

> Die in `.env` geschriebenen Heartbeat-URLs zeigen bewusst auf
> `host.docker.internal`, nicht auf `localhost`: sie werden **aus dem
> `oneuptime-sync`-Container heraus** aufgerufen, und dort wäre
> `localhost` der Container selbst. OneUptime läuft in einem eigenen
> Compose-Projekt, also nicht auf demselben Docker-Netzwerk.

### Manuell

Für Cloud-Trial (https://oneuptime.com) oder eigene Einrichtung:

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

## DocuWare-Cluster: App-Owner-Tiefe + einfache Nutzeransicht

Zeigt beide Zielgruppen eines Monitoring-Stacks am selben Beispiel: **tief
technisch für App-Owner** (Grafana) und **einfach für Endnutzer**
(OneUptime-Statuspage) - für dieselbe, fiktive Anwendung.

**Aufbau** (`docker-compose.yml`, `scripts/docuware-metrics-exporter.py`):
- `demo-docuware-site`: lokale Fixture (nginx, immer erreichbar), im
  Blackbox-Job als `docuware.pyur.com` beschriftet - **keine echte
  Netzwerkanfrage an eine reale pyur.com-Domain**, exakt dasselbe
  Relabel-Muster wie bei `demo-broken-site`
- `docuware-metrics-exporter`: synthetischer Prometheus-Exporter, liefert
  plausible, leicht schwankende Metriken für WAF, IIS, MSSQL-Cluster
  (inkl. Replikations-Lag und APM-Query-Dauer), VMware-Host und Hardware
  (SAN/Strom/Kühlung) - keine echte Integration, nur Zahlen für ein
  glaubwürdiges Dashboard

**Grafana-Dashboard "DocuWare – Cluster-Status (App-Owner)"**
(`grafana/dashboards/docuware-cluster-status.json`, automatisch
provisioniert): Gesamtstatus-Stat oben, dann Website/WAF, IIS,
MSSQL-Cluster, VMware, Hardware - alle Panel-Queries gegen die echten
(synthetischen) Prometheus-Metriken.

**OneUptime-Statuspage** (einfache Nutzeransicht): ein Eintrag "DocuWare
(Dokumentenmanagement)" in eigener Gruppe auf der Statusseite
**IT-Services (Mitarbeiter)**. Bewusst **kein** Heartbeat-Monitor wie
`demo-broken-site`, sondern ein `Manual`-Monitor: der Witz dieses
Beispiels ist "Seite erreichbar, Login kaputt" - eine Unterscheidung, die
reines HTTP-Probing gar nicht treffen kann. Ein Heartbeat-Monitor würde
beim nächsten erfolgreichen Ping automatisch wieder auf "Operational"
springen (die Fixture IST erreichbar) und dem manuell gesetzten
"Degraded" unten entgegenlaufen - und zusätzlich einen eigenen "kein
Heartbeat"-Incident parallel zum handgeschriebenen Major Incident
erzeugen. `Manual` hält die Geschichte eindeutig: der Incident selbst ist
das Signal.

**Beispiel Major Incident** (von `seed-oneuptime.sh` angelegt, nicht
automatisch ausgelöst): **"DocuWare | Anmeldung in DocuWare nicht
möglich"**, Schweregrad "Major Incident", Status **"In Behebung"** (eigener
ITIL-v4-Remediation-Status, zwischen "Acknowledged" und "Resolved"
angelegt, da OneUptime standardmäßig nur Identified/Acknowledged/Resolved
seedet). Beschreibung erklärt die Auswirkung für Mitarbeitende und
referenziert im Text den echten BMC-Vorfall `INC000000222127` als
Markdown-Link. Bewusst nicht auto-aufgelöst und unabhängig vom
Erreichbarkeits-Monitor (Login-Ausfall ≠ Site nicht erreichbar - wie bei
echten Statuspages).

**Live vorführen:** `./break-docuware.sh` lässt den Metrics-Exporter
MSSQL-Knoten db2 ausfallen, WAF-Blocks hochschnellen und IIS/APM
langsamer werden - sichtbar im Grafana-Dashboard binnen ~15-30s (nächster
Prometheus-Scrape). `./fix-docuware.sh` macht es rückgängig. Unabhängig
vom DocuWare-Erreichbarkeits-Heartbeat, der die ganze Zeit gesund bleibt.

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
| OneUptime-Monitor / Statuspage | Monitor kippt auf "Offline", Status page zeigt den Service als beeinträchtigt | nach der "Not Recieved In Minutes"-Kulanzzeit (vom Seeding auf 5 min gesetzt) |

Voraussetzung für die letzten beiden Zeilen: `ONEUPTIME_DEMO_HEARTBEAT_URL`
in `.env` gesetzt - das erledigt `./seed-oneuptime.sh` automatisch (bzw.
`./start-demo.sh --with-oneuptime`). Ohne das bleibt es beim Prometheus-/
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

## Live-E-Mail-Demo (Mailpit)

Zusätzlich zu den Mockups unten gibt es einen **echten, live auslösbaren**
E-Mail-Versand - kein Mockup, sondern die tatsächliche
OneUptime-Benachrichtigungs-Pipeline (echter SMTP-Handshake, echter
Subscriber-Notification-Cronjob), nur dass die Mail in einem lokalen
Postfach statt im echten Internet landet.

- `mailpit`-Container (`docker-compose.yml`) fängt jede ausgehende Mail
  lokal ab - Web-Oberfläche unter **http://localhost:8025**, es verlässt
  nichts diesen Rechner
- `seed-oneuptime.sh` konfiguriert OneUptimes **Global SMTP**
  (`/api/global-config`, die feste Singleton-Zeile mit ID
  `00000000-0000-0000-0000-000000000000` - nur per Master-Admin-Session
  beschreibbar, unser Demo-Account ist das automatisch) auf
  `host.docker.internal:1025` und legt einen Demo-Abonnenten
  (`mitarbeiter@pyur-demo.local`) auf der Zertifikats- und der
  IT-Services-Seite an (`isSubscriptionConfirmed: true`, sonst überspringt
  der Notification-Cron ihn als unbestätigt)

**Live auslösen:** `./break-demo.sh` - nach Ablauf des
Heartbeat-Fensters (Default 5 Minuten) legt OneUptime automatisch einen
Incident an; der Subscriber-Notification-Cronjob läuft jede Minute und
verschickt daraufhin eine echte E-Mail. Insgesamt bis zu ~6 Minuten bis
sie in Mailpit auftaucht. Schon die Anlage des Abonnenten selbst löst
sofort eine Bestätigungsmail aus - guter erster Funktionstest, ohne auf
den Heartbeat zu warten.

## Benachrichtigungs-Mockups (E-Mail, Teams, Mobil)

`mockups/` enthält statische, in sich geschlossene HTML-Seiten, die
zeigen, wie eine Statuspage-Benachrichtigung für Abonnenten in
verschiedenen Kanälen aussehen würde - reine Anschauungs-Mockups für die
Management-Demo (Teams/Mobil bleiben Mockup - **keine echten
Integrationen**, es wird nichts verschickt, kein Teams-Webhook/
SMS-Gateway angebunden; nur E-Mail ist oben live). Jede Seite
zeigt sowohl den DocuWare-Major-Incident als auch einen alltagsnahen
Minor Incident ("E-Mail-Versand verzögert") - zwei Schweregrade, eine
Mitarbeiterperspektive.

**Einstieg:** `mockups/index.html` - Übersichtsseite mit anklickbaren
Kacheln zu allen drei Kanälen. Einzeln direkt aufrufbar:

- `mockups/benachrichtigung-email.html` - Posteingang-Ansicht (E-Mail-Client), zwischen mehreren Nachrichten klickbar
- `mockups/benachrichtigung-teams.html` - Microsoft-Teams-Kanal mit Adaptive Cards,
  gleicher "Vorfall auslösen"/"Zurücksetzen"-Trick wie beim Mobil-Mockup -
  Nachrichten poppen animiert im Kanalverlauf auf
- `mockups/benachrichtigung-mobil.html` - Smartphone-Sperrbildschirm (Push) + SMS-Verlauf,
  per "Vorfall auslösen"-Knopf **animiert** (reines CSS/JS, kein Backend) -
  Benachrichtigungen federn wie echte Push-Meldungen von oben ein,
  SMS-Bubbles poppen nacheinander auf; "Zurücksetzen" spielt es erneut ab

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
