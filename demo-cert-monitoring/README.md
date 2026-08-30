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

> **Login-Rate-Limit angehoben.** OneUptime begrenzt Logins standardmäßig
> auf 10 Versuche/15 Minuten pro Konto - beim wiederholten Ausführen von
> Seed-/Break-/Fix-Skripten während der Entwicklung (und beim mehrfachen
> Neustart von `start-demo.sh --with-oneuptime`) reicht das schnell nicht
> mehr, live selbst mehrfach erlebt (`HTTP 429: Too many sign-in
> attempts`). `oneuptime-selfhosted/oneuptime/config.env` setzt deshalb
> `IDENTITY_LOGIN_RATE_LIMIT_PER_ACCOUNT_PER_WINDOW=200` (Standard-Rationale
> und Env-Var-Name in `Common/Server/Middleware/IdentityRateLimit.ts`
> nachgelesen). Diese Variable wurde vom `app`-Service in
> `docker-compose.base.yml` bisher nicht durchgereicht - eigener,
> minimaler Patch dort ergänzt (nur diese eine neue Variable, sonst
> nichts an OneUptimes eigenem Compose-Setup verändert). Nur für dieses
> lokale Demo-/Dev-Setup sinnvoll, nicht für ein echtes Deployment mit
> echten Sicherheitsanforderungen.

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
   - **Postmortem-Beispiel mit Zeitachse und Root-Cause-Analyse (#135):**
     "Jira-Ticketsuche zeitweise nicht verfügbar" (Anmeldung &
     Ticket-Suche, vor 35 Tagen, `Resolved`) - anders als die drei
     Sicherheitsereignisse oben (nur `declaredAt` zurückdatiert) hat
     dieser Incident eine echte Zeitachse aus vier zeitversetzten
     `IncidentPublicNote`-Einträgen (erkannt → untersucht → Ursache
     gefunden → behoben, je mit eigenem `postedAt`) plus eine
     strukturierte Analyse im nativen `Incident.rootCause`-Feld
     (Auslöser/Auswirkung/Behebung/Follow-up-Maßnahmen) - beide Felder
     im tatsächlichen OneUptime-Quellcode bestätigt
     (`Common/Models/DatabaseModels/{Incident,IncidentPublicNote}.ts`),
     nicht in die Beschreibung hineingetextet.

   Alle Dienste sind feste `Manual`-Monitore ohne Sensor, starten
   automatisch grün und werden nur gezielt (z.B. via Wartung/Incident) auf
   einen anderen Status gesetzt.
3. **Statusseite Standort Leipzig** - standortbezogene Facility-IT:
   Internet, Netzwerk, WLAN, Drucker - inkl. geplanter Druckerwartung
   (nutzerorientiert: was/wann/Alternative/Kontakt) und **abgeschlossen:**
   "Wartung Netzwerk-Switches (Rechenzentrum Leipzig)".

   **Live auslösbarer Druckerwartungs-Prozess (#148):** Neben der
   statischen "nächsten Freitag"-Wartung oben zeigt `./break-printer.sh`
   den kompletten Prozess auf Knopfdruck: Drucker meldet eine Störung →
   die IT terminiert kurzfristig eine Wartung ("Kurzfristige Wartung –
   Drucker (Hauptgebäude)", 2 Stunden Vorlauf) → die Standort-Leipzig-
   Statusseite zeigt sie sofort an. Der Monitor `Drucker (Hauptgebäude)`
   bleibt dabei bewusst **Operational** - eine Scheduled Maintenance
   kündigt eine Auswirkung nur an, sie erzeugt selbst keine; der Drucker
   ist also bis zum Beginn der Wartung nicht eingeschränkt. `./fix-printer.sh`
   setzt die Wartung auf "Completed" und reiht sie damit neben "Wartung
   Netzwerk-Switches" als weiteren abgeschlossenen Eintrag ein. Eigener,
   separat benannter Eintrag statt Wiederverwendung der statischen
   Freitags-Wartung - gleiches Prinzip wie das live auslösbare vierte
   Sicherheitsereignis oben, das ebenfalls neben statischen Einträgen
   steht statt sie zu überschreiben (`scripts/printer_maintenance.py`,
   kein Import von `seed_oneuptime.py`, siehe dortige Begründung). Auch im
   Demo-Kontrollzentrum (`./control-panel.sh`) als Karte "Druckerwartung
   (Prozess)" auslösbar - **mit expliziter Admin-/Nutzer-Trennung**, damit
   die Demo die beiden Rollen nebeneinander zeigt statt nur eine Seite:
   "Admin" verlinkt direkt auf OneUptimes Scheduled-Maintenance-Liste
   (`/scheduled-maintenance-events`, wo Techniker die Wartung tatsächlich
   anlegen), "Nutzer" auf die Standort-Leipzig-Statusseite selbst sowie
   auf `mockups/benachrichtigung-email.html#drucker` - ein URL-Hash, der
   das E-Mail-Mockup direkt auf die Druckerwartungs-Nachricht springen
   lässt (`selectMail()` im Mockup wertet `location.hash` aus), statt dass
   in der Vorführung erst durch den Posteingang geklickt werden muss.

**Kontrollzentrum-Review, alle Karten:** bei der Gelegenheit auch die
übrigen sechs Karten in `./control-panel.sh` auf fehlende Sublinks
durchgesehen - Zertifikats-Karte bekam einen direkten Link zur
Zertifikate-Statusseite (Nutzer-Sicht, vorher nur Grafana/Prometheus/
Mailpit), Customer-Care-Karte einen Link zum neuen
Avaya-Callcenter-Dashboard (das Szenario lässt live auch dessen
Warteschlange volllaufen, war aber nirgends verlinkt), und Security-Karte
einen direkten Statusseiten-Link statt nur des generischen
OneUptime-Logins. Jede Karte gruppiert ihre Links jetzt zusätzlich unter
"Admin"/"Nutzer"-Labels statt einer undifferenzierten Liste. **Farblich
unterscheidbar:** jede Karte hat eine eigene Akzentfarbe (farbiger oberer
Rand + leicht eingefärbter Hintergrund, nicht nur das kleine Icon wie
vorher) - sieben klar unterscheidbare Farbtöne, damit man während einer
Vorführung nicht erst den Kartentitel lesen muss, um die richtige Karte
zu finden.

**Alle Termine werden bei jedem Lauf neu relativ zu "heute" berechnet**
(Patchday 3 läuft immer gerade jetzt, abgeschlossene Wartungen liegen
immer 6-10 Tage in der Vergangenheit, die Druckerwartung immer am
kommenden Freitag, das Firewall-Fenster immer Mi–Fr der nächsten Woche),
damit die Demo auch Wochen später noch aktuell aussieht. **Ausnahme,
bewusst (#135):** ist das Firewall-Fenster einer bereits bestehenden
Ankündigung schon vorbei, wird es bei einem erneuten `./seed-oneuptime.sh`
**nicht** erneut in die nächste Woche verschoben - die Ankündigung bleibt
als vergangener Eintrag stehen (verschwindet dadurch automatisch von der
aktiven Statusseite, siehe die `iso()`-Zeitzonen-Anmerkung oben zur
Overview-API-Filterung) statt bei jedem Lauf unbegrenzt in die Zukunft zu
wandern.

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

**Vier weitere OneUptime-Produktbereiche** (nicht nur Monitore/
Statusseiten/Incidents - je ein Beispiel, im Kontext der bestehenden
Demo-Story statt isoliert):

- **On-Call Duty**: Richtlinie "IT-Betrieb On-Call" mit einer
  Eskalationsregel ("Nach 5 Minuten eskalieren" → Team "Owners", das
  jedes Projekt automatisch anlegt und in dem der Demo-Account bereits
  Mitglied ist - kein zusätzliches Team/User-Setup nötig). Am DocuWare-
  Incident **und** am live auslösbaren Sicherheits-Incident
  (`security_incident.py`) verankert (`Incident.onCallDutyPolicies`) -
  eine Richtlinie, zweimal im Kontext genutzt, statt zwei isolierten
  Beispielen. Ohne echten Push-/SMS-/E-Mail-Provider in diesem lokalen
  Stack bleibt der Effekt visuell (Eskalationskette auf der
  Incident-Detailseite), keine echte Benachrichtigung.

  **Direkt verlinkt statt gesucht:** die Eskalationsregel selbst und ihr
  tatsächliches Auslösen liegen in OneUptime mehrere Klicks tief in den
  On-Call-Duty-Einstellungen vergraben - für eine Vorführung zu langsam
  zu finden. `seed_oneuptime.py` schreibt die (über Reseeds hinweg
  stabile) Policy-ID deshalb in `.oneuptime-demo-summary`;
  `control_panel_server.py` baut daraus zwei Direktlinks, die auf den
  Sicherheits- und DocuWare-Festplatte-Karten im Kontrollzentrum
  erscheinen: **"On-Call-Eskalation"** (`.../on-call-duty/policies/<id>/escalation`
  - zeigt die konfigurierte 5-Minuten-Regel) und **"On-Call-Protokoll"**
  (`.../on-call-duty/policies/<id>/execution-logs` - zeigt jedes
  tatsächliche Auslösen der Regel, live nachvollziehbar nach jedem
  `break-security.sh`/`break-docuware-disk.sh`). Beide Routen aus dem
  echten OneUptime-Quellcode bestätigt (`RouteMap.ts`,
  `ON_CALL_DUTY_POLICY_VIEW_ESCALATION`/`_EXECUTION_LOGS`), nicht geraten.
- **Service Catalog**: drei `Service`-Einträge (DocuWare, Customer Care,
  Standort Leipzig – Netzwerk) mit Beschreibung, Farbe und Owner-Team
  "Owners" - dieselben Komponenten, die die Demo an anderer Stelle schon
  ausführlich zeigt, hier als knappe Katalogeinträge. **Einschränkung
  recherchiert und bestätigt:** diese OneUptime-Version hat
  `ServiceMonitor`/`ServiceDependency` per Schema-Migration entfernt
  (`1779739410559-MigrationName.ts` / `1779277271302-DropServiceDependencyTable.ts`)
  - ein Service lässt sich über die API **nicht mehr** mit bestehenden
  Monitoren verknüpfen oder mit einer manuellen Abhängigkeits-Kante zu
  einem anderen Service versehen; Abhängigkeiten werden inzwischen
  ausschließlich aus echten OpenTelemetry-Trace-Spans abgeleitet. Bewusst
  keine vorgetäuschte Abhängigkeitsgrafik gebaut, wo die API keine
  erlaubt.
- **Telemetry (Logs)**: ein paar realistische Log-Zeilen für einen
  Dienst `docuware-login` (z. B. "Verbindung zur Datenbank
  docuware-db:5432 fehlgeschlagen"), passend zur DocuWare-Vorfall-Story.
  Reines OTLP/HTTP-JSON per `POST /otlp/v1/logs` mit
  `x-oneuptime-token`-Header - kein OpenTelemetry-SDK/Collector nötig.
  Ein `TelemetryIngestionKey` wird dafür einmalig angelegt
  (`secretKey` kommt als typisiertes Feld `{"_type": "ObjectID", "value":
  ...}` zurück, live bestätigt statt geraten). Der Dienst `docuware-login`
  entsteht dabei automatisch als eigener Service-Catalog-Eintrag (Name
  aus dem `service.name`-Resource-Attribut) - ohne vorherige manuelle
  Anlage. Logs nur beim ersten Anlegen des Ingestion-Keys verschickt
  (kein Spam bei jedem erneuten Lauf); Inhalt am besten direkt in
  OneUptime unter Telemetry → Logs prüfen, die Logs-Analytics-Daten
  liegen in ClickHouse und sind nicht über die generische
  `/api/<model>/get-list`-Route abfragbar wie der Rest dieses Skripts.
- **Security Events / Detection Rules**: dieselbe "Verdächtige
  Anmeldeversuche"-Story, die schon als statusseiten-Incident erzählt
  wird, jetzt zusätzlich als echte SIEM-artige Security Events - eine
  Quell-IP mit fehlgeschlagenen Anmeldungen für vier verschiedene
  Benutzerkonten plus eine automatische IP-Sperre, per generischem JSON
  gegen `POST /security-events/v1/ingest` gesendet (Feld-Aliasse wie
  `message`/`status`/`user`/`source_ip`/`vendor`, keine OCSF/UDM-Kenntnis
  nötig - Format live anhand `Common/Utils/SecurityEvent/GenericNormalizer.ts`
  bestätigt). Dazu eine echte **Sigma-Detection-Rule**
  ("Verdächtige Anmeldeversuche (Credential Stuffing)", 1-Minuten-Takt,
  gruppiert nach Quell-IP, zählt eindeutige betroffene Benutzerkonten,
  Schwelle 3) - Sigma-Syntax gegen den offiziellen Testfall
  `SigmaRuleParser.test.ts` ("Possible Brute Force") abgeglichen statt
  geraten. **Live end-to-end verifiziert:** Die Regel hat innerhalb einer
  Minute automatisch einen Alert erzeugt (`[Detection] Verdächtige
  Anmeldeversuche (Credential Stuffing) — 203.0.113.44`) - der komplette
  Pfad von Rohdaten bis Alarm funktioniert tatsächlich, nicht nur die
  Konfiguration.

  > **Bug gefunden & behoben: Detection Rule feuerte nicht.**
  > Auswertungsfenster laufen laut Quellcode (`EvaluateDetectionRules.ts`)
  > ausschließlich vorwärts ab `lastEvaluatedAt` - nie rückwirkend. Die
  > Security Events waren anfangs wie die historischen Incidents 13-15
  > Minuten in die Vergangenheit datiert; dadurch lagen sie dauerhaft
  > außerhalb jedes je ausgeführten Auswertungsfensters (4 Zyklen lang
  > `lastMatchAt: null` bestätigt). Fix: Zeitstempel auf nahezu "jetzt"
  > gesetzt - danach hat der allererste Auswertungszyklus sofort
  > gematcht.

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

## Standort Leipzig – Netzwerk-Topologie (Grafana, Facility-IT)

`grafana/dashboards/leipzig-network-topology.json` +
`scripts/leipzig-network-exporter.py` - eigenes LAN am Standort Leipzig
(nicht zu verwechseln mit den Customer-Care-S2S-VPN-Strecken **ins**
Rechenzentrum Leipzig, siehe oben): ein Internet-Router, ein Core-Switch
im Keller, 10 Access-Switches über 4 Bereiche auf einer Etage
(Verwaltung ×3, Vertrieb ×3, Technik ×2, Besprechung ×2).

- **Übersicht**: Geräte insgesamt, Geräte offline, Ø CPU-Auslastung,
  max. Temperatur
- **Netzwerk-Topologie** (Node-Graph, gleiches Muster wie die
  Customer-Care-Topologie oben, von Anfang an mit der korrekten
  `labelsToFields`+gescopetem-`merge`-Transformation gebaut - siehe
  Bug-Hinweis im Customer-Care-Abschnitt): Router → Core → je Access-
  Switch, Kantenfarbe nach Uplink-Status (rot = offline)

  > **Zweiter Bug gefunden & behoben (live vom Nutzer gemeldet: "zeigt
  > keine Switche an"):** Anders als bei Customer Care (dort liefern
  > Health-*Formeln* den generischen Feldnamen `Value`) fragt dieses
  > Panel **rohe Metriken direkt** ab (`net_device_up`,
  > `net_uplink_up`) - und eine rohe Metrik-Abfrage benennt ihr
  > Wertfeld nach der Metrik selbst, live per `/api/ds/query` bestätigt.
  > Die `organize`-Transformation rannte auf `renameByName: {"Value":
  > "mainStat"}` ins Leere, weil dieses Feld unter diesem Namen nie
  > existierte - `mainStat` blieb leer, das Node-Graph-Panel hatte keine
  > sinnvollen Werte zum Rendern. Zusätzlich erschwert: die Edges-Query
  > vereinigt zwei *verschiedene* Metriken (`net_uplink_up` für die 10
  > Access-Switch-Kanten, `net_device_up` für die Router-Core-Kante) -
  > beide Feldnamen mussten auf `mainStat` umbenannt werden, nicht nur
  > einer. Fix live verifiziert (Feldnamen-Fix im Dashboard-JSON,
  > Grafana-Reprovisionierung bestätigt) - die tatsächliche Darstellung
  > bitte im Browser gegenchecken.
- **Geräte im Detail** (Tabelle): Online-Status, CPU, Temperatur je Gerät

`./break-leipzig-network.sh` lässt einen Access-Switch
(Access-Switch Vertrieb-2) offline gehen - Uplink bricht weg, Node-Graph
zeigt ihn rot, "Geräte offline" springt auf 1. `./fix-leipzig-network.sh`
macht es rückgängig. Live durchgetestet (`net_device_up`/`net_uplink_up`
vor/nach dem Break bestätigt).

**Jetzt auch im Demo-Kontrollzentrum:** dieses Szenario hatte trotz
fertigem Break/Fix-Skript und Dashboard bislang keine eigene Karte in
`./control-panel.sh` - beim Review aller Kontrollzentrum-Karten
aufgefallen und als siebte Karte "Standort Leipzig – Netzwerk-Vorfall"
ergänzt (`net_uplink_up{device="Access-Switch Vertrieb-2"}` als
Live-Status, gleiches Prinzip wie bei den anderen Prometheus-Karten).
Bewusst Grafana-only wie die DocuWare-Cluster- und Customer-Care-Karten -
reine Facility-IT-Beobachtung ohne OneUptime-Incident.

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
> (`filter: {id: "byRefId", options: "<refId>"}`), sonst wären alle
> 6 Standort-Linien wieder zu einer einzigen verketteten Route
> zusammengefasst worden. Dieselbe Ursache betraf auch die
> Zertifikats-Tabelle im Website-Dashboard (siehe unten) - vermutlich
> seit deren ursprünglicher Erstellung unbemerkt leer/falsch.

> **Nachtrag, echter Root-Cause-Bug: der gescopte `merge` griff nie.**
> Live vom Nutzer gemeldet ("Agenten-Status je Standort - keine Anzeige",
> dasselbe bei der Leipzig-Topologie/-Tabelle) - **nach** dem oben
> beschriebenen Feldnamen-Fix. Ursache im Grafana-Bundle nachvollzogen
> (nicht geraten): der `filter`, der einen Transformationsschritt auf
> die Frames EINER Ziel-Query beschränkt, braucht einen **Frame**-Matcher
> aus der `FrameMatcherID`-Registry (`byRefId`) - `byFrameRefID` (mit
> dem alle betroffenen Panels ursprünglich gebaut waren) existiert nur in
> der komplett anderen `FieldMatcherID`-Registry, dort für
> `fieldConfig.overrides`-Matcher gedacht. Eine unbekannte Matcher-ID im
> `filter` eines Transformationsschritts lässt das ganze Panel leer
> bleiben, statt einen sichtbaren Fehler zu zeigen. Betraf **alle** neu
> gebauten Panels mit gescoptem `merge`: Customer-Care-Panel 7 (Agenten)
> und 17 (Kartenlinien, 6× gescoped) und 22 (Topologie), Leipzig-Panel 5
> (Node-Graph) und 6 (Geräte-Tabelle), Avaya-Panel 21 (Agenten-Status) -
> insgesamt 18 `filter`-Objekte in 3 Dashboard-Dateien korrigiert, live
> per API bestätigt (`byRefId` jetzt überall gespeichert, keine
> `byFrameRefID`-Reste mehr).

> **Dritter Nachtrag: Legende zeigte "Value #A"/"Value #B"/"Value #C"
> statt echter Namen.** Nach dem `byRefId`-Fix flossen die Daten (live
> vom Nutzer bestätigt), aber `merge` + `joinByField` benennen die
> zusammengeführte Werte-Spalte offenbar generisch `Value` um, egal wie
> die Rohmetrik hieß - Grafana disambiguiert mehrere gleichnamige
> `Value`-Felder dann selbst über ihre ursprüngliche Abfrage-RefId
> ("Value #A" usw.). Die `organize`-Umbenennung auf den (falsch
> angenommenen) Rohmetrik-Namen griff dadurch ins Leere. Robuster Fix:
> statt zu raten, wie das Feld nach dem Join heißt, ein
> `fieldConfig.overrides`-Eintrag pro Abfrage mit dem **Feld**-Matcher
> `byFrameRefID` (hier - anders als im `filter` einer Transformation -
> korrekt, da `fieldConfig.overrides` tatsächlich die
> `FieldMatcherID`-Registry braucht) plus `displayName`/Farbe/Einheit/
> Schwellenwert direkt auf der jeweiligen RefId, unabhängig vom
> tatsächlichen Zwischennamen. Betraf alle vier Panels mit
> `joinByField`: Customer-Care-Panel 7, Leipzig-Panel 6, Avaya-Panel 21,
> und vorsorglich auch die Zertifikats-Statustabelle (Website-Dashboard
> Panel 4, war dort nicht gemeldet, aber dieselbe Konstruktion - jetzt
> überall dieselbe robuste Methode statt zwei verschiedener,
> fehleranfälliger Ansätze).

> **Vierter Nachtrag: die beiden Node-Graph-Panels zeigten weiterhin
> "No data" - trotz zwischenzeitlich "bestätigt" (siehe Historie oben).**
> Live vom Nutzer gemeldet ("Netzwerk-Topologie – Leipzig-Hub ↔ Standorte
> zeigt no data"). Diesmal per Playwright/Chromium tatsächlich im Browser
> nachgeprüft statt nur strukturell/per API - und dabei festgestellt,
> dass **auch das als "funktionierend" dokumentierte Leipzig-Netzwerk-
> Node-Graph-Panel nie wirklich lief**, nur nie jemand mit echtem
> Browser-Zugriff nachgeschaut hatte. Zwei zusammenwirkende, per
> Panel-Inspector (`Inspect → JSON → Panel data`) am tatsächlichen
> Datenframe verifizierte Root-Causes, beide nicht offensichtlich aus der
> Dashboard-JSON ablesbar:
> 1. `organize`s `renameByName` setzt **nur** `field.config.displayName`,
>    nicht den echten `field.name` - bestätigt am Datenframe (`"name":
>    "company", "config": {"displayName": "title"}`, der Rohname bleibt
>    unverändert). Node-Graph verlangt aber den **echten** Feldnamen
>    (`id`/`title`/`mainStat`/`source`/`target`) - eine nur umbenannte
>    Anzeige reicht nicht.
> 2. Der gescopte `merge`-Schritt benennt die einzige numerische Spalte
>    grundsätzlich zu `Value #<refId>` um, komplett unabhängig vom
>    ursprünglichen Metrik- oder Abfragenamen (auch mit einem via
>    `label_replace(..., "__name__", ...)` erzwungenen eindeutigen Namen
>    reproduziert) - vermutlich ein Nebeneffekt von `merge`s internem
>    `outerJoinDataFrames` beim Fehlen eines gemeinsamen Join-Schlüssels.
>
> Robuster Fix (kein Rätselraten über Zwischennamen mehr nötig): für
> String-Felder (`id`/`title`/`subTitle`/`source`/`target`) direkt in der
> PromQL per `label_replace` ein Label mit dem **exakt** benötigten Namen
> erzeugen, damit `labelsToFields` das Feld von Anfang an korrekt nennt.
> Für die numerische `mainStat`-Spalte, die `merge` ohnehin umbenennt,
> einen gescopten `calculateField`-Transformationsschritt (`mode:
> "reduceRow"`, `reduce.include: ["Value #<refId>"]`, `alias: "mainStat"`)
> **nach** `merge` einfügen - der erzeugt ein neues Feld mit echtem
> `field.name`, statt ein bestehendes umzubenennen. Betraf beide
> Node-Graph-Panels im Stack (Leipzig-Panel 5, Customer-Care-Panel 22) -
> beide jetzt per Screenshot (nicht nur API) bestätigt korrekt gerendert.
>
> Lehre für künftige Node-Graph-Panels in diesem Stack: **API-/JSON-
> Verifikation reicht bei diesem Panel-Typ nicht aus** - `renameByName`
> wirkt dort nie wie erwartet, ein echter Browser-Check (z. B. via
> Playwright, `npx playwright install chromium`) ist die einzige
> verlässliche Probe.

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
  (`filter: {id: "byRefId", options: "A"|"B"}`), damit die 7
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

## Avaya Call Center – Betriebsansicht (Grafana, Callcenter-Optimierung)

`grafana/dashboards/avaya-callcenter-operations.json` - fokussierte
Zusatzansicht für Callcenter-Manager, inspiriert vom klassischen
Avaya/BCMS-Operator-Dashboard-Layout aus [diesem
Blogpost](https://blog.upinget.com/2021/02/07/using-grafana-to-monitor-avaya-call-center/)
(Trunk-/VDN-/Queue-/Agenten-/KPI-Panels über die BCMS- und
CallAnalytics-APIs). Ergänzt die breitere Customer-Care-Dashboard oben
um die Kennzahlen, an denen ein Callcenter-Manager tatsächlich Personal-
und SLA-Entscheidungen festmacht - teils neue Metriken im Exporter
(`scripts/customer-care-metrics-exporter.py`):

- **KPIs**: Anrufe in Warteschlange, ältester wartender Anruf,
  **Service Level** (Anteil der Anrufe innerhalb der SLA-Zielzeit
  beantwortet, branchenüblich 80/20), **ACHT** (Average Call Handling
  Time - Gesprächs- plus Nachbearbeitungszeit, neue Metrik
  `cc_avaya_acht_seconds`, bewusst getrennt von der reinen
  Warteschlangen-Wartezeit)
- **Trunk & Warteschlange**: SIP-Trunk-Mitglieder nach Status
  (idle/in_use/unknown, neue Metrik `cc_avaya_trunk_members`) sowie der
  Warteschlangen-Verlauf über Zeit
- **Agenten**: Agenten-Status je Standort (verfügbar / im Gespräch /
  Nachbearbeitung-Pause) als gestapelter Balken-Chart - dritter
  Agenten-Status `cc_avaya_agents_not_ready` neu ergänzt, für eine
  vollständigere ACD-Statusverteilung als im Hauptdashboard oben

Von Anfang an mit der korrekten `labelsToFields`+gescopetem-`merge`
(`byRefId`, nicht `byFrameRefID` - siehe Bug-Hinweis oben)
+`joinByField`-Transformation gebaut. Alle neuen Metriken live gegen
Prometheus verifiziert.

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

**Zweites, unabhängiges Vorfall-Szenario - Festplatte läuft voll:**
`./break-docuware-disk.sh` lässt das SAN-Volume "Dokumentenspeicher" auf
92-98% Auslastung klettern (Panel "Speicherplatz-Auslastung
(SAN-Volumes)", rot ab 90%) - Datenbank- und Log-Volume bleiben
unverändert im Normalbereich, gleiche isolierte Blast-Radius-Erzählung
wie beim MSSQL/WAF-Szenario oben. `./fix-docuware-disk.sh` macht es
rückgängig. Nutzt einen eigenen State-File
(`/tmp/docuware-disk-state` im Container) unabhängig von
`break-docuware.sh`, damit beide Szenarien einzeln oder zusammen
vorgeführt werden können.

Anders als das MSSQL/WAF-Szenario (nur Prometheus/Grafana) spielt dieses
Szenario **komplett durch** - Grafana ist hier nur der Anfang:
- **OneUptime, live**: `break-docuware-disk.sh` legt zusätzlich einen
  echten Incident an ("DocuWare | Speicherplatz kritisch
  (Dokumentenspeicher)", `scripts/docuware_disk_incident.py`, gleiches
  Break/Fix-Muster wie `security_incident.py`, inkl. desselben
  Delete-und-Neuanlegen-Fixes für ein erneutes Auslösen aus dem
  Resolved-Zustand). Verknüpft mit dem bestehenden DocuWare-Monitor (der
  auf Degraded wechselt) und der bestehenden On-Call-Richtlinie
  "IT-Betrieb On-Call" - dieselbe Richtlinie wie beim
  DocuWare-Login-Incident, kein Duplikat.
- **Mitarbeiter-Benachrichtigung**: läuft automatisch über denselben,
  bereits verifizierten Weg wie bei den anderen echten Incidents in
  dieser Demo (OneUptime-Statuspage-Update + Abonnenten-E-Mail via
  Mailpit) - keine zusätzliche Mock-Benachrichtigung nötig.
  Übersprungen, falls OneUptime nicht läuft (`./start-demo.sh` ohne
  `--with-oneuptime`) - der Prometheus/Grafana-Teil funktioniert dann
  trotzdem unverändert.
- **BMC-ITSM-Ticket fürs Bearbeiter-Team**: `mockups/backend-bmc-itsm.html`
  hat jetzt zwei unabhängig auslösbare Szenarien in derselben
  Vorfalls-Warteschlange (Buttons "Login-Vorfall auslösen" /
  "Speicherplatz-Vorfall auslösen") - das neue Ticket
  (`INC000000222190`) referenziert im Detail-Modal die On-Call-Richtlinie
  und den verknüpften OneUptime-Incident, genau wie das bestehende
  Login-Ticket.
- **Vorfallsrollen (OneUptime, echtes Produkt-Feature)**: fünf eigene,
  echte OneUptime-User (nicht der eine `demo@example.com`-Account) -
  Jonas Weidner, Lena Hoffmann, Tobias Krüger, Kristin Albrecht, Paul
  Neumann - angelegt in `seed_oneuptime.py` per `/api/identity/signup`
  (self-hosted verifiziert E-Mails automatisch, kein Bestätigungs-Mail-
  Umweg) und der Team "Members" hinzugefügt. `break-docuware-disk.sh`
  weist sie den vier Standard-Vorfallsrollen zu: Incident Commander
  (Jonas), Communications Lead (Lena), Responder (Tobias), Observer -
  **zwei** Personen (Kristin + Paul), um die "Multiple"-Fähigkeit dieser
  einen Rolle zu zeigen. Idempotent (prüft bestehende
  incident-member-Zuweisungen vor dem Anlegen, da OneUptime eine doppelte
  Zuweisung ablehnt). Die Karte im Kontrollzentrum bekommt nach
  "Vorfall auslösen" automatisch einen Link "Vorfallsrollen (OneUptime)"
  direkt zum Rollen-Tab des gerade aktiven Incidents - geschrieben von
  `docuware_disk_incident.py` in `.docuware-disk-incident.json`
  (gitignored), weil die Incident-ID bei jedem Neu-Auslösen wechselt
  (Delete-und-Neuanlegen aus dem Resolved-Zustand) und ein fest
  verdrahteter Link sonst sofort veralten würde.

## IT-Ops – Gesamtübersicht (Grafana, alle Bereiche)

`grafana/dashboards/it-ops-overview.json` - die sechste Dashboard-Perspektive,
diesmal nicht pro Bereich, sondern **quer über alle**: eine Ampel-Kachel je
Bereich (Website & Zertifikate, DocuWare-Cluster, Customer Care, Standort
Leipzig - jede grün/rot nach demselben "Gesamtstatus (1 = gesund)"-Muster,
das die Einzeldashboards schon verwenden) und ein Klick auf eine Kachel
springt direkt ins zugehörige Detail-Dashboard (Grafanas Panel-`links`).

Der eigentliche Punkt dieses Dashboards: **dieselben Prometheus-Metriken
sehen aus jeder Perspektive anders aus.** Ein großes Markdown-Textpanel
("Weitere Perspektiven") verlinkt explizit gruppiert nach Zielgruppe:

- **Technische Sicht (Grafana)** - die anderen 5 Dashboards, je mit ihrer
  Zielgruppe (App-Owner/Technical Owner/Facility-IT)
- **Endnutzer-Sicht** - die öffentliche OneUptime-Statuspage über die
  Dashboard-Variable `$oneuptime_url` (Default `http://localhost/`, im
  Dashboard selbst änderbar, ohne die JSON-Datei zu editieren - passend zum
  selben Muster wie in `mockups/index.html`)
- **Weitere Werkzeuge** - Demo-Kontrollzentrum, Prometheus (die eigentliche
  Quelle der Wahrheit hinter allen Dashboards), Mailpit, Benachrichtigungs-
  Mockups

Zusätzlich verlinkt das Dashboard selbst (Grafanas Dashboard-`links`, oben
im Toolbar-Dropdown) zu den anderen 5 - Navigation geht also sowohl über
das sichtbare Textpanel als auch nativ über Grafana. Im
[Demo-Kontrollzentrum](#demo-kontrollzentrum) taucht es als erste Karte
unter "Dashboards" auf.

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
Kacheln zu allen drei Kanälen, plus einer grün abgesetzten Kachel, die
(anders als die übrigen) keine Vorschau ist, sondern die echte, laufende
OneUptime-Instanz dieser Demo in einem neuen Tab öffnet - Standard-URL
`http://localhost/` (passend zu `oneuptime-selfhosted/setup.sh`s eigenem
Default), per `?oneuptime=<url>` in der Adresszeile der Übersichtsseite
überschreibbar, ohne die Datei zu editieren. Einzeln direkt aufrufbar:

- `mockups/benachrichtigung-email.html` - Posteingang-Ansicht (E-Mail-Client), zwischen mehreren Nachrichten klickbar
- `mockups/benachrichtigung-teams.html` - Microsoft-Teams-Kanal mit Adaptive Cards,
  gleicher "Vorfall auslösen"/"Zurücksetzen"-Trick wie beim Mobil-Mockup -
  Nachrichten poppen animiert im Kanalverlauf auf. **Jede Nachricht ist
  klickbar** (Karten und die einfache Wartungs-Textnachricht) und öffnet
  ein Detail-Modal (Status, betroffenes System, Beschreibung, bei den
  beiden Incidents zusätzlich ein Verlauf) - gleiches Muster wie das
  BMC-ITSM-Mockup, nur im Teams-Farbschema. Eine vierte Nachricht zeigt
  die **Vorfallsrollen-Zuweisung** für den DocuWare-Festplatte-Incident
  (Incident Commander/Communications Lead/Responder/2× Observer,
  @-erwähnt) - derselbe Klick-ins-Detail-Modal-Trick, hier mit den fünf
  echten Demo-Usern aus `seed_oneuptime.py`. Der Chat-Bereich hat eine
  feste Höhe mit internem Scroll (wie echtes Teams) - `playTeams()`
  scrollt automatisch zur neuesten Nachricht mit, sonst würde die vierte
  Nachricht unterhalb des sichtbaren Bereichs verschwinden (live beim
  Testen mit Playwright/Chromium aufgefallen, nicht auf den ersten Blick
  aus der HTML/JS ersichtlich).
- `mockups/benachrichtigung-mobil.html` - Smartphone-Sperrbildschirm (Push) + SMS-Verlauf,
  per "Vorfall auslösen"-Knopf **animiert** (reines CSS/JS, kein Backend) -
  Benachrichtigungen federn wie echte Push-Meldungen von oben ein,
  SMS-Bubbles poppen nacheinander auf; "Zurücksetzen" spielt es erneut ab.
  Vierte Push-Meldung: persönliche On-Call-Benachrichtigung "Rolle
  zugewiesen: Incident Commander" - dieselbe Vorfallsrollen-Story wie im
  Teams-Mockup, aus der Perspektive des benachrichtigten Handys.
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
- `mockups/monitoring-checkmk.html` - **Werkzeug-Vergleich**: derselbe
  DocuWare-Stack (Server/DB/Loadbalancer/Webseite), hier aus Sicht eines
  klassischen, agentenbasierten Monitoring-Tools (CheckMK-Optik) statt
  Grafana - Host-/Service-Tabelle mit Tactical-Overview-Kacheln
  (Hosts/OK/Warn/Kritisch). "Störung auslösen" schlägt denselben
  Datenträger-voll-Fall wie im Grafana-Dashboard/Kontrollzentrum auf einen
  Service-Check nieder und schreibt einen Eintrag ins Alarmierungs-Log;
  "Beheben" macht es rückgängig. Rein statisches Mockup (kein echter
  CheckMK-Container, keine Agenten/Checks) - Zweck ist der visuelle
  Werkzeug-Vergleich, nicht eine funktionierende zweite Monitoring-Instanz.
- `mockups/oneuptime-network-map.html` - **Konzept: Live-Netzwerkkarte via
  LLDP/CDP, in OneUptime-Optik**: dieselbe Standort-Leipzig-Topologie wie
  im Grafana-Node-Graph-Panel, hier aber mit Port-zu-Port-
  Nachbarschaftsdetails (lokaler Port, Nachbargerät, Port am Nachbarn,
  LLDP/CDP), wie eine klassische Netzwerk-Auto-Discovery sie liefern
  würde - ein Feature, das OneUptime **nicht** hat (Abhängigkeitsgraphen
  kommen dort ausschließlich aus echten OpenTelemetry-Traces, siehe
  Service-Catalog-Abschnitt oben). Gerät anklicken zeigt seine
  Nachbarschaftstabelle. Statische Daten (keine echte SNMP-/LLDP-MIB-
  Abfrage möglich, da die Switches synthetisch sind) - Zweck ist der
  visuelle Konzeptvergleich, nicht eine funktionierende Discovery.

## Demo-Kontrollzentrum

`./control-panel.sh` startet eine kleine lokale Seite
(**http://localhost:7100**) - der zentrale Startpunkt für die ganze
Demo, nicht nur für die Vorfall-Skripte:

- Fünf Szenario-Karten (Zertifikat, DocuWare-Cluster, DocuWare-Festplatte
  voll, Customer Care, Sicherheits-Vorfall), je mit kurzer Story,
  Illustration, Live-Status und Break-/Fix-Buttons statt
  Terminal-Aufrufen. Die ersten vier lesen ihren Status direkt aus
  Prometheus; der Sicherheits-Vorfall lebt in
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

## Ruhigere Zeitreihen-Graphen

Die Zeitreihen-Panels wirkten zu "spikig" für eine Management-Demo (alle
15s ein neuer, unabhängig ausgewürfelter Messwert). Zwei Stellschrauben,
beide angewendet:

- **Weniger Jitter an der Quelle**: die `wave()`-Hilfsfunktion in allen
  drei synthetischen Exportern (`scripts/*-metrics-exporter.py`) erzeugt
  jetzt ±1 % Rauschen statt ±3 % um die eigentliche Sinuskurve - die
  sichtbare Bewegung bleibt (kein flacher Strich), die Kurve wirkt aber
  deutlich ruhiger.
- **Weiche Linien-Interpolation in Grafana**: alle 23 Zeitreihen-Panels
  über alle vier Dashboards (`fieldConfig.defaults.custom.lineInterpolation:
  "smooth"`) - rein optisch, ändert nichts an den Daten selbst, rundet
  nur die Verbindungslinie zwischen den Punkten.

Scrape-Intervall (15s) bewusst unverändert gelassen - die überall in
dieser README dokumentierten "~15-30s"-Reaktionszeiten der Break-/
Fix-Skripte hängen daran.

## Bei Code-Änderungen: was lädt automatisch, was braucht einen Neustart

- **Lädt automatisch:** Grafana-Dashboards (`grafana/dashboards/*.json`,
  Datei-Provisioner scannt alle ~30s neu), `mockups/*.html` und
  `scripts/control-panel.html` (werden bei jedem Request frisch von der
  Platte gelesen) - einfach speichern und (bei Dashboards) kurz warten
  bzw. (bei HTML) den Browser-Tab neu laden.
- **Braucht einen Neustart:** die `*-metrics-exporter.py`-Skripte (laufen
  in einem langlebigen Container, Python liest die Datei nur beim
  Container-Start) und `scripts/control_panel_server.py` (läuft als
  eigener Host-Prozess, kein Hot-Reload). `./reload-demo.sh` erledigt
  beides in einem Schritt - live getestet.

## Demo-Daten zurücksetzen (Konfiguration bleibt erhalten)

`./reset-demo-data.sh` leert Prometheus' aufgelaufene Metrik-Historie
(Graphen starten wieder bei null), lässt aber jede Konfiguration
unangetastet (Targets, Alert-Regeln, Grafana, OneUptime). **Bewusst nur
Prometheus** - für OneUptimes eigene Historie (Incident-Timelines, Logs,
Security Events, bereits ausgelöste Alerts) gibt es keinen einzelnen
"Historie löschen, Konfiguration behalten"-API-Aufruf, der nicht riskiert,
die geseedete Struktur mit zu zerstören; `./seed-oneuptime.sh` konvergiert
die Struktur ohnehin bei jedem Lauf neu, danach erneut ausführen für einen
konsistenten Zustand. Enthält `docker volume rm` (löscht Daten) - bewusst
nicht automatisch mitgetestet, bitte gezielt selbst ausführen.

## Demo täglich frisch halten (#135)

`./refresh-demo.sh` - gedacht für einen täglichen Cron-Job, aber jederzeit
auch manuell ausführbar (jeder Schritt ist idempotent/best-effort):

1. **Heilt Liegengebliebenes:** ruft alle `fix-*.sh` best-effort auf, falls
   von einer früheren Vorführung noch ein `break-*.sh` offen war - jeder
   Fehler ("nichts zu beheben") wird verschluckt statt das Skript
   abzubrechen. Läuft der Kern-Stack gerade nicht, wird der komplette
   Lauf übersprungen (nichts ist einer Zielgruppe gegenüber sichtbar
   kaputt, wenn die Demo gar nicht deployed ist).
2. **Rotiert einen frischen, bereits aufgelösten Vorfall ein**
   (`scripts/refresh_demo.py`) aus einem Themen-Pool (Jira-Benachrichtigungen,
   Kalenderfreigaben, VPN-Neuverbindung, Blueant, WLAN, Jira-Anhänge) -
   damit eine Demo auch Wochen später noch einen kürzlich behobenen
   Vorfall zum Zeigen hat statt immer dieselben drei
   Wochen alten Sicherheitsereignisse. Hält maximal zwei rotierende
   Einträge gleichzeitig aktiv und löscht den ältesten, bevor ein neuer
   dazukommt - welche Incidents zur Rotation gehören, steht in
   `.refresh-demo-state.json` (gitignored), nicht in einem Text-Marker im
   Vorfall selbst, damit die rotierten Einträge genauso aussehen wie jeder
   andere echte Vorfall auf der Statusseite.

Als Cron-Job:

```cron
0 6 * * * cd /pfad/zu/demo-cert-monitoring && ./refresh-demo.sh >> /tmp/refresh-demo.log 2>&1
```

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
