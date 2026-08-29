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

> **Bug gefunden & behoben: `outlook.office.com` zeigte fälschlich
> "offline".** Live nachvollzogen (`blackbox_exporter`-Debug-Probe): der
> Dienst ist real erreichbar, antwortet auf einen einfachen synthetischen
> GET aber mit HTTP 417 statt 2xx - bestätigt mit einem echten
> Chrome-User-Agent (gleiches Ergebnis), liegt also nicht an fehlenden
> Headern, sondern an Microsofts Edge/WAF-Verhalten gegenüber
> automatisierten Clients, nicht an einer echten Störung. Fix: ein
> zusätzliches Blackbox-Modul `http_2xx_or_ms_417`
> (`blackbox/blackbox.yml`), das 417 zusätzlich akzeptiert, per
> Prometheus-Relabeling **nur für dieses eine Ziel** aktiviert
> (`prometheus.yml`, `__param_module`-Override auf
> `outlook.office.com`-Match) - alle anderen Ziele bleiben beim strengen
> reinen 2xx-Check. Live durchgetestet: `probe_success` sprang auf 1,
> `oneuptime-sync` pingt den Heartbeat wieder, der OneUptime-Monitor
> erholt sich.

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
   - **Weitere interne Dienste** (VPN, Blueant) mit `displayDescription`
     als Performance-Einordnung in Alltagssprache ("Antwortzeit: normal")
   - **DocuWare** (Dokumentenmanagement) - siehe eigener Abschnitt unten
   - Wartungen "Patchday Server Gruppe 3" (Status "Ongoing", Blueant
     betroffen und auf "Degraded" gesetzt), "Wartungsfenster VPN-Gateway"
     (Status "Scheduled"), **abgeschlossen:** "Patchday Server Gruppe 1 & 2"
     (Status "Completed" - erzählerischer Vorgänger von Gruppe 3)
   - Ankündigung "Geplantes Firewall-Upgrade (Barracuda)"
   - **Vergangene Sicherheitsereignisse** (mitarbeiterverständlich, drei
     bereits abgeschlossene Incidents): "Verdächtige Anmeldeversuche
     erkannt und blockiert" (Anmeldung/SSO, vor 14 Tagen), "Phishing-
     E-Mail-Welle abgewehrt" (E-Mail senden/empfangen, vor 28 Tagen),
     "Außerplanmäßiges Sicherheitsupdate eingespielt" (VPN-Zugang, vor 21
     Tagen) - alle sofort als `Resolved` angelegt, bewusst ohne
     Fachbegriffe formuliert und mit einer klaren Entwarnung im Text
     ("Es kam zu keinem unbefugten Zugriff" etc.), damit sichtbar wird,
     dass Sicherheitsvorfälle transparent kommuniziert werden, statt nur
     intern zu bleiben. Datum kommt über `Incident.declaredAt` (dynamisch
     relativ zu "heute", wie jedes andere Datum in diesem Skript) - live
     bestätigt: erscheinen korrekt in `timelineIncidents` der
     Status-Page-Overview-API, neben dem aktiven DocuWare-Incident.
   - **Live auslösbares viertes Sicherheitsereignis:** `./break-security.sh`
     setzt "Anmeldung (SSO)" auf Degraded und legt den echten, aktiven
     Incident "Ungewöhnliche Anmeldeaktivität wird untersucht" an
     (Status "Identified", gleiche mitarbeiterverständliche Sprache wie
     oben). `./fix-security.sh` postet ein echtes Auflösungs-Update
     (`IncidentPublicNote`, löst bei aktivem Mailpit-Abonnenten eine
     echte E-Mail aus) und setzt Incident auf Resolved sowie den Monitor
     zurück auf Operational - danach ist es ein vierter Eintrag neben den
     drei statischen Ereignissen. `scripts/security_incident.py`
     (Login/API-Zugriff, kein Import von `seed_oneuptime.py` - das würde
     dessen kompletten Seed-Lauf erneut auslösen, da es beim Import statt
     hinter `if __name__=="__main__"` läuft). Erneutes Auslösen von
     `break-security.sh` während der Vorfall schon aktiv ist, ist
     absichtlich ein No-op statt eines Fehlers - OneUptime erzwingt
     Vorwärts-only-Statuswechsel (`In Behebung` → `Identified` schlägt
     serverseitig mit HTTP 400 fehl, live bestätigt) und das Skript prüft
     das vorher ab. Live end-to-end durchgetestet: Vorfall auslösen →
     erneut auslösen (No-op, kein Fehler) → beheben → alle vier
     Sicherheitsereignisse korrekt in `timelineIncidents`, nur DocuWare
     bleibt aktiv.

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
lokalen Demo-URL unsichtbar, deshalb ungenutzt) - dasselbe Bild erscheint
auch im Kopf jeder Benachrichtigungs-E-Mail (bestätigt per Mailpit,
siehe unten). Alle drei Statusseiten (Zertifikate, IT-Services, Leipzig)
verwenden dasselbe generierte **PYUR-Monitoring-Wortmarke**
(`assets/pyur-monitoring-logo.svg`) statt dreier unterschiedlicher
Icons - konsistenter fürs Management-Publikum. Das reale DocuWare-Logo
(`assets/docuware-logo.png`, © DocuWare Corporation, [CC BY-SA
4.0](https://de.wikipedia.org/wiki/Datei:Docuware_logo_2018_bg_white_0.png)
via Wikimedia Commons) bleibt im Repo, wird aber nicht mehr als
Seiten-Logo eingebunden. `File`-Objekte sind in OneUptime unveränderlich
(kein Update-Recht) - ein Logo-Wechsel legt daher immer eine neue Datei
an; die lokalen `.oneuptime-logo-<seite>.id`-Marker müssen dafür gelöscht
werden, sonst wird die alte, gecachte Datei-ID weiterverwendet.

**Gruppen auf allen drei Statusseiten sind standardmäßig eingeklappt** -
nur Gruppen, die gerade eine Beeinträchtigung enthalten, klappen sich
automatisch auf (`StatusPageGroup.isExpandedByDefault`, am Ende von
`seed_oneuptime.py` für jede Gruppe live anhand des aktuellen
Monitor-Status neu gesetzt). Das ist eine statische Momentaufnahme beim
Seed-Lauf, kein Live-Verhalten der Statusseite selbst - nach einem
`break-*.sh`/`fix-*.sh` muss `./seed-oneuptime.sh` erneut laufen, damit
sich der Auf-/Zuklapp-Zustand nachzieht.

> **Stabile URLs?** Geprüft: echtes CNAME-Custom-Domain-Routing
> (`StatusPageDomain`) verifiziert beim Setzen von `isVerified` aktiv per
> DNS-TXT-Abfrage gegen echte Nameserver - für eine rein lokale Demo ohne
> echte Domain (auch `*.localhost`) nicht erfüllbar, live getestet und
> verworfen. Nicht nötig ist es ohnehin: `seed-oneuptime.sh` findet
> Seiten/Monitore über ihren Namen wieder statt sie neu anzulegen, die
> `/status-page/<id>`-URLs bleiben über Neustarts hinweg stabil (in dieser
> Session über zahlreiche Läufe hinweg bestätigt).

> **Bug gefunden & behoben: Ankündigung erschien nicht auf der Statuspage.**
> `iso()` (der Helfer, der alle dynamischen Daten in dieses Skript
> formatiert) nahm lokale Wall-Clock-Zeit (`datetime.now()`, auf diesem
> Rechner Europe/Berlin) und hängte unkonvertiert ein `Z` (UTC) an -
> während der Sommerzeit lag jedes dynamische Datum dadurch ~2h in der
> Zukunft gegenüber der echten UTC-Uhr des OneUptime-Servers. Betraf
> **alle** dynamischen Termine (Ankündigung, Wartungen, Incident-Updates),
> sichtbar wurde es zuerst bei der Ankündigung: OneUptimes eigene
> Overview-API filtert Ankündigungen auf `showAnnouncementAt < jetzt(UTC)`
> - die noch nicht "gestartete" Ankündigung blieb unsichtbar, obwohl alle
> Felder (inkl. `showAnnouncementsOnStatusPage`) korrekt gesetzt waren.
> Live per `/status-page-api/overview/<id>` nachvollzogen
> (`activeAnnouncements: []` trotz korrekt aussehender Daten), Fix
> (`iso()` konvertiert jetzt über die lokale Zeitzone nach UTC) live
> verifiziert (`activeAnnouncements` zeigt die Ankündigung sofort nach
> dem Fix).

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

## Website & Zertifikats-Dashboard (Grafana, App-Owner)

`grafana/dashboards/website-cert-monitoring.json` - technisches
Gegenstück zur Zertifikate-Statusseite, für den App-Owner statt für
Endnutzer. Überarbeitet nach dem Vorbild von [Grafana Dashboard #13922
"Certificates Expiration (X509 Certificate
Exporter)"](https://grafana.com/grafana/dashboards/13922-certificates-expiration-x509-certificate-exporter/)
- übernommen wurden die **Ideen** (Übersichts-Stats mit Schwellenwerten,
Top-Aussteller-Tabelle, sortierte "kürzeste Restlaufzeit"-Tabelle,
Dashboard-Variablen für die Schwellenwerte), nicht die Dashboard-Datei
selbst: #13922 basiert auf dem `x509-certificate-exporter` (Kubernetes
Secrets/Host-Zertifikatsdateien, eigene Metriken wie
`x509_cert_not_after`) - unser Stack nutzt `blackbox_exporter`
(`probe_ssl_earliest_cert_expiry`, `probe_success`,
`probe_ssl_last_chain_info`), ein komplett anderes Metrik-Schema für
HTTP(S)-Synthetic-Checks statt Kubernetes/Dateisystem. Ein 1:1-Import
wäre an den Metriknamen gescheitert.

- **Übersicht** (Zeile mit Stats): Überwachte Websites, Nicht erreichbar,
  Zertifikate abgelaufen, Läuft ab in `$critical_threshold`/
  `$warning_threshold` Tagen (Dashboard-Variablen, Default 7/30 Tage,
  direkt im Dashboard änderbar), kürzeste Restlaufzeit
- **Details je Website**: die bestehende Statustabelle (Erreichbarkeit,
  Zertifikats-Restlaufzeit, Antwortzeit je Website)
- **Analyse** (neu): "Top Zertifikatsaussteller" (`count by (issuer)
  (probe_ssl_last_chain_info)`) und "Kürzeste Restlaufzeit" (sortierte
  Tabelle, `sortBy`-Transformation)
- **Verlauf**: die bestehenden Zeitreihen (Antwortzeit, Restlaufzeit je
  Website)

> **Bug gefunden & behoben (vermutlich seit Erstellung unentdeckt): die
> Statustabelle "Status je Website" war vermutlich nie korrekt befüllt.**
> Live per `/api/ds/query` bestätigt: `probe_success`/
> `probe_ssl_earliest_cert_expiry`/`probe_duration_seconds` liefern für 4
> überwachte Ziele 4 separate 1-Zeilen-Frames statt einer Tabelle -
> `instance` existierte nur als Feld-Metadaten, nicht als echte Spalte,
> die `joinByField`-Transformation (Verknüpfung über `instance`) griff
> dadurch ins Leere. Fix: `labelsToFields` vor `joinByField` ergänzt
> (siehe ausführlicher Bug-Hinweis im Customer-Care-Abschnitt unten für
> die technischen Details des allgemeinen Musters). Live mit
> `./break-demo.sh`/`./fix-demo.sh` durchgetestet: "Zertifikate
> abgelaufen" sprang korrekt von 0 auf 1 und zurück.

## Customer Care: Standortübersicht für den technischen Owner (Grafana)

Reines Grafana-Dashboard (kein OneUptime-Anteil diesmal) für den
technischen Owner eines verteilten Customer-Care-Service - Hauptziel:
technische Störungen erkennen, Performance/Auslastung sehen.

**Modellierter Service** (`scripts/customer-care-metrics-exporter.py`):
Telefonie (Avaya ACD, SIP-Trunk), Citrix (Agenten-Desktops), eine
Kundensupport-App, eine Rechnungswesen-App, Cognigy (Chat-/Voicebot -
die einzige Cloud-/SaaS-Komponente, alles andere on-prem) inkl. dessen
Anfragen an die interne LLM (`llm.pyur.com`), sowie die zugrunde
liegende Infrastruktur. Customer Care ist auf **6 Standorte** verteilt,
die jeweils per Site-to-Site-VPN an das Rechenzentrum in **Leipzig**
angebunden sind: Berlin, Dresden, Chemnitz, Halle (Saale), Rostock,
Erfurt.

> **Bug gefunden & behoben: Balken-Charts und das Topologie-Panel blieben
> leer.** Live per `/api/ds/query` nachvollzogen: eine Prometheus-Instant-
> Tabellenabfrage mit mehreren Zeitreihen liefert Grafana **eine separate
> 1-Zeilen-Datenframe pro Zeitreihe** - Labels (z. B. `site`) existieren
> nur als Feld-Metadaten, nicht als echte Spalte, und der Wertname wird
> bei einer reinen Metrik-Abfrage nach der Metrik selbst benannt (z. B.
> `cc_avaya_agents_available`, nicht generisch `Value`). Panels wie
> Table/Bar-Chart/Node-Graph brauchen aber echte Zeilen in **einer**
> Frame. Fix, angewendet auf jedes betroffene Panel: `labelsToFields`
> (Labels → echte Felder) gefolgt von `merge` (mehrere gleich-geformte
> 1-Zeilen-Frames einer Abfrage → eine mehrzeilige Tabelle) bzw. bei
> mehreren verschieden geformten Abfragen zusätzlich `joinByField` zum
> Verknüpfen. Für die Verbindungslinien der Deutschlandkarte (siehe
> unten) musste `merge` sogar **pro Ziel-Query gescoped** laufen
> (`filter: {id: "byFrameRefID", options: "<refId>"}`), sonst wären alle
> 6 Standort-Linien wieder zu einer einzigen verketteten Route
> zusammengefasst worden. Dieselbe Ursache betraf auch die
> Zertifikats-Tabelle im Website-Dashboard (siehe unten) - vermutlich
> seit deren ursprünglicher Erstellung unbemerkt leer/falsch.

**Grafana-Dashboard "Customer Care – Standortübersicht (Technical
Owner)"** (`grafana/dashboards/customer-care-overview.json`, 22 Panels,
automatisch provisioniert):
- Gesamtstatus-Stats oben (Störungserkennung auf einen Blick: Anzahl
  Standorte mit VPN-Störung, Warteschlange, Wartezeit)
- Telefonie/Avaya ACD, Citrix, Kundensupport-/Rechnungswesen-App,
  Cognigy/LLM, Infrastruktur - je eigene Zeile
- **Agenten je Standort** (verfügbar / im Gespräch): gruppierter
  vertikaler Balken-Chart statt Rohtabelle - `labelsToFields` + zwei
  quer-gescopte `merge`-Schritte (je Abfrage) + `joinByField` (auf
  `site`) führen "Verfügbar"/"Im Gespräch" zusammen, `organize` blendet
  `Time`/`__name__`/`instance`/`job` aus und benennt `site` in "Standort"
  sowie die beiden Metrikspalten in "Verfügbar"/"Im Gespräch" um
- **Bandbreitenauslastung (%), VoIP-Qualität (MOS-Score), Latenz zum RZ
  Leipzig, gleichzeitige Anrufe** je Standort: ebenfalls Balken-Charts
  statt Rohtabellen (gleiches Entrümpeln), zusätzlich mit Schwellenwert-
  Einfärbung (z. B. MOS < 3.5 rot, 3.5-4.0 gelb, ≥ 4.0 grün)
- **Deutschlandkarte** (Grafana-Geomap-Panel, echte Koordinaten der 6
  Standorte + Leipzig als Hub, drei Layer):
  - **Basiskarte**: Esri "World Light Gray Canvas" als generischer
    XYZ-Tile-Layer (`services.arcgisonline.com`) statt `osm-standard` oder
    Grafanas eingebautem `carto`-Basemap-Typ - Letzterer verlangt
    inzwischen einen CARTO-API-Key (live bestätigt: die
    `basemaps.cartocdn.com`-Kacheln tragen mittlerweile ein
    "API KEY REQUIRED"-Wasserzeichen). Die Esri-Kacheln sind weiterhin
    kostenlos ohne Anmeldung nutzbar (derselbe Anbieter, den Grafanas
    eigener XYZ-Layer-Standardwert bereits verwendet, gleiches
    URL-Schema, live per Kachel-Abruf bestätigt) und genauso
    minimalistisch (helles Grau, nur Landesgrenzen, keine
    Straßen/POI-Details). Kartenausschnitt per
    `view: {id: "fitData", padding: 32}` automatisch auf die 7 Punkte
    zugeschnitten statt eines festen Zoom-Levels.
  - **Standorte (Photos-Layer)**: statt schlichter Farbpunkte zeigt jeder
    Standort ein kleines rundes Icon - Büro-Symbol für die 6
    Call-Center-Standorte, Server-/Rack-Symbol für den Leipziger Hub
    (`assets/icons/*.svg`, als Data-URI im `photo`-Label des Exporters
    eingebettet, da nur die Skriptdatei selbst in den Exporter-Container
    gemountet ist). Die Icon-**Farbe kodiert direkt den Gesundheitsstatus**
    (grün/gelb/rot) - der Photos-Layer selbst unterstützt anders als
    Marker/Route keine wertabhängige Einfärbung, deshalb entscheidet der
    Exporter serverseitig, welches der drei vorgerenderten Icons er
    ausliefert.
  - **Standort-Beschriftung**: ein zweiter, unsichtbarer Marker-Layer
    (Opacity 0, nur fürs Text-Rendering) zeigt den frei erfundenen
    Call-Center-Firmennamen jedes Standorts unter dessen Icon
    (`company`-Label, z. B. "NordCom Kundenkontakt Berlin") - der
    Photos-Layer selbst hat keine eigene Text-Option.
  - **VPN-Verbindungen (Route-Layer)**: Linienfarbe kommt aus einer
    dreistufigen Health-Formel (`(vpn_up*2) - (vpn_up*(auslastung>=85%))`):
    0 = VPN down (rot), 1 = VPN up aber Link überlastet ≥ 85 % (gelb),
    2 = gesund (grün) - dieselbe Formel bestimmt auch die Icon-Farbe. Die
    6 Verbindungslinien Leipzig↔Standort sind bewusst 6 **getrennte**
    2-Punkt-Queries (nicht eine verkettete Route über alle Punkte), damit
    jede Linie unabhängig radial vom Hub ausgeht statt die Standorte der
    Reihe nach zu verbinden. Jedes der 6 Ziele braucht dafür seinen
    Hub+Standort in **einer** Frame (siehe Bug-Hinweis oben) - deshalb 6
    einzeln auf ihre `refId` gescopte `merge`-Schritte statt eines
    einzigen globalen `merge`, das sonst den 6-fach wiederholten
    Hub-Punkt über alle Ziele hinweg zu einer einzigen 7-Punkte-Frame
    zusammengefasst und damit genau die verkettete Route zurückgebracht
    hätte, die dieses Design eigentlich vermeidet.

  Technischer Hinweis: Prometheus-Labels kommen aus Grafanas Query-Engine
  nur als Feld-Metadaten, nicht als eigene Spalten - das Geomap-Panel
  braucht aber benannte Felder für `location.mode: coords`, deshalb hängt
  am Panel eine `labelsToFields`-Transformation. Alle 7 Kartenqueries
  (Gesamtansicht + 6 Hub-Standort-Paare) live gegen Prometheus auf die
  erwartete Zeilenzahl und das Vorhandensein von `photo`/`company`
  geprüft; die tatsächliche Kartendarstellung selbst lässt sich ohne
  Grafana-Image-Renderer-Plugin (nicht installiert) nicht als Screenshot
  verifizieren - bitte einmal im Browser gegenprüfen.
- **Netzwerk-Topologie** (Grafana-Node-Graph-Panel, Panel 22): dieselbe
  Hub-Spoke-Struktur wie die Karte, aber schematisch statt geografisch -
  ein Standort-Ausfall ist hier auf einen Blick als roter/gelber Knoten
  bzw. rote/gelbe Kante erkennbar, unabhängig von der Position auf der
  Landkarte. Zwei Queries pro Node-Graph-Konvention: **Nodes**
  (`site`→`id`, `company`→`title`, Health-Wert→`mainStat`, plus Leipzig
  als eigener Knoten) und **Edges** (eine Zeile je Standort, `source`/
  `target`-Felder per verkettetem PromQL-`label_replace()` erzeugt - der
  erste Aufruf stempelt jeder Zeile das feste Label `source="Leipzig
  (RZ)"` auf, der zweite kopiert das vorhandene `site`-Label nach
  `target`, sodass keine Grafana-seitigen Konstanten-Transformationen
  nötig sind). Gleiche dreistufige Health-Formel/Farbcodierung wie Karte
  und Balken-Charts. War zunächst leer (siehe Bug-Hinweis oben) - Fix:
  `labelsToFields` + je einen `merge`-Schritt gescoped auf Query A bzw. B
  (`filter: {id: "byFrameRefID", options: "A"|"B"}`), damit die 7
  Nodes-Frames und 6 Edges-Frames getrennt zu genau den zwei Tabellen
  zusammengeführt werden, die das Node-Graph-Panel erwartet, statt sich
  gegenseitig zu vermischen. Beide Queries live gegen Prometheus auf die
  erwartete Zeilenzahl (7 Nodes, 6 Edges) und die Felder `id`/`title`/
  `mainStat`/`source`/`target` geprüft; die tatsächliche Darstellung
  selbst weiterhin ohne Image-Renderer-Plugin nicht per Screenshot
  prüfbar - bitte im Browser gegenchecken.

Alle 34 Panel-Queries live gegen Prometheus verifiziert. Baseline
bewusst "geschäftig, aber gesund" (~45-75 % Auslastung mit sichtbarer
Bewegung, keine Störung) - `./break-customer-care.sh` lässt live den
VPN-Link nach **Chemnitz** hart einbrechen (Paketverlust, schlechter
MOS-Score, Bandbreiten-Kollaps) und die Avaya-Warteschlange
volllaufen; `./fix-customer-care.sh` macht es rückgängig. Live
verifiziert: Chemnitz-VPN ging auf 0, "Standorte mit VPN-Störung"
sprang auf 1, die Warteschlange auf 39 Anrufe.

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

**Vorfallsbericht mit echten Mitarbeiter-Updates:** zusätzlich zur
statischen Erstbeschreibung drei zeitlich gestaffelte
`IncidentPublicNote`-Einträge (`/api/incident-public-note`, dieselbe
Statuspage-Timeline, die auch bei echten Vorfällen Updates zeigt) -
"Problem bestätigt" → "Ursache eingegrenzt, Neustart läuft" →
"Neustart durchgeführt, wird noch beobachtet". Bewusst **kein**
"Behoben"-Update, der Incident bleibt ja absichtlich offen ("In
Behebung"). Zeitstempel relativ zu "jetzt" beim Seed-Lauf (25/14/4 Minuten
zurück), idempotent über exakten Notiztext (kein Duplizieren bei
erneutem Lauf). `shouldStatusPageSubscribersBeNotifiedOnNoteCreated:
true` - beim ersten Anlegen bekommt der Demo-Abonnent
(`mitarbeiter@pyur-demo.local`) diese Updates auch tatsächlich per Mail
über Mailpit zugestellt, genau wie beim Live-E-Mail-Demo unten.

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
  Nachrichten poppen animiert im Kanalverlauf auf. **Jede Nachricht ist
  klickbar** (Karten und die einfache Wartungs-Textnachricht) und öffnet
  ein Detail-Modal (Status, betroffenes System, Beschreibung, bei den
  beiden Incidents zusätzlich ein Verlauf) - gleiches Muster wie das
  BMC-ITSM-Mockup, nur im Teams-Farbschema
- `mockups/benachrichtigung-mobil.html` - Smartphone-Sperrbildschirm (Push) + SMS-Verlauf,
  per "Vorfall auslösen"-Knopf **animiert** (reines CSS/JS, kein Backend) -
  Benachrichtigungen federn wie echte Push-Meldungen von oben ein,
  SMS-Bubbles poppen nacheinander auf; "Zurücksetzen" spielt es erneut ab
- `mockups/backend-bmc-itsm.html` - **Backend-Sicht statt Mitarbeiter-Sicht**:
  zeigt, wie OneUptime im Hintergrund einen BMC-ITSM-Vorfall meldet und ein
  Ticket eröffnet. "Vorfall auslösen" spielt eine dreistufige
  Integrations-Leiste ab (OneUptime erkennt Störung → REST-API-Aufruf an BMC
  ITSM → Ticket angelegt), danach poppt das neue Ticket
  (`INC000000222127`, dieselbe Nummer wie im DocuWare-Major-Incident, für
  eine durchgängige Story) oben in eine Vorfalls-Warteschlange und wechselt
  kurz danach automatisch von "Neu" auf "Zugewiesen". **Jede Zeile in der
  Warteschlange ist klickbar** und öffnet ein Ticket-Detail-Modal
  (Priorität, Status, Gruppe, Kategorie, betroffene CI, Melder, SLA-Ziel,
  Beschreibung, Verlauf/Worklog) - für das laufende DocuWare-Ticket liest
  das Modal Status/Gruppe live aus der Zeile aus, damit es nach
  "Vorfall auslösen" immer den aktuellen Stand zeigt statt einer
  eingefrorenen Kopie.

## Demo-Kontrollzentrum

`./control-panel.sh` startet eine kleine lokale Seite
(**http://localhost:7100**) - der zentrale Startpunkt für die ganze
Demo, nicht nur für die Vorfall-Skripte:

- Vier Szenario-Karten (Zertifikat, DocuWare, Customer Care,
  Sicherheits-Vorfall), je mit kurzer Story, Illustration, Live-Status
  und Break-/Fix-Buttons statt Terminal-Aufrufen. Die ersten drei lesen
  ihren Status direkt aus Prometheus; der Sicherheits-Vorfall lebt in
  OneUptime selbst (Manual-Monitor + Incident, kein Prometheus-Metrik
  dahinter) - der Kontrollserver hält dafür einen gecachten Login-Token
  über alle 5-Sekunden-Polls hinweg vor, statt sich bei jedem Poll neu
  anzumelden (OneUptimes Login-Endpunkt ist auf 10 Versuche/15 Min.
  begrenzt - ein Login pro Poll hätte den Demo-Account innerhalb von
  Sekunden gesperrt, live selbst erlebt beim Testen dieses Features).
- **Hub-Bereich** darunter, gruppiert in "Statusseiten
  (Mitarbeiter/Kunden)" (alle drei OneUptime-Statusseiten, Links live
  aus `.oneuptime-demo-summary` gelesen statt hartkodiert), "Dashboards
  (App-Owner/Technical Owner)" (die drei Grafana-Dashboards) und
  "Werkzeuge" (OneUptime, Mailpit, Benachrichtigungs-Mockups,
  Prometheus)

Sicherheit:
- Bindet **ausschließlich an 127.0.0.1** - nie über das Netzwerk
  erreichbar
- Die Buttons führen ausschließlich die bereits im Repo geprüften
  Skripte (`break-*.sh`/`fix-*.sh`) über eine feste Whitelist aus - keine
  freie Eingabe, kein beliebiger Shell-Zugriff (live geprüft: ein
  Testaufruf mit unbekannter Aktion wird mit HTTP 400 abgelehnt)
- Live end-to-end verifiziert: Klick auf "Vorfall auslösen" hat den
  echten DocuWare-Cluster-Vorfall ausgelöst, der Status-Indikator ist auf
  "gestört" gesprungen, "Beheben" hat zurückgesetzt

`scripts/control_panel_server.py` (reines Python-Stdlib, kein
zusätzliches Paket) + `scripts/control-panel.html`. Läuft bewusst **im
Vordergrund außerhalb von Docker** (Ctrl+C stoppt es) statt als weiterer
`docker-compose.yml`-Service - `./start-demo.sh` weist am Ende auf
diesen Befehl hin, startet ihn aber nicht automatisch mit.

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
