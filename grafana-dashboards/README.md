# IT-Infra-Ops-Dashboards (Grafana)

Rollenbasierte Grafana-Dashboards als **Demo** - eigenständig von der
`demo-cert-monitoring/`-Verkaufsdemo (andere Zielgruppe, anderer Zweck), aber nach demselben
Prinzip gebaut: alle vier Exporter liefern **synthetische Beispieldaten**, der Stack ist also
sofort mit Inhalt lauffähig, ganz ohne echtes SQL Server/Apache/Server/vCenter im Hintergrund.

| Rolle | Dashboard | Nachgebildeter Exporter | Mock-Exporter |
|---|---|---|---|
| DB-Admins | MS SQL Server – Best Practices | `sql_exporter` | `mock-exporters/mssql_mock_exporter.py` |
| Webserver-Admins | Apache2 | `apache_exporter` | `mock-exporters/apache_mock_exporter.py` |
| Systemadmins | Node Exporter Full | `node_exporter` | `mock-exporters/node_mock_exporter.py` |
| Systemadmins | VMware vSphere Host | `vmware_exporter` | `mock-exporters/vmware_mock_exporter.py` |

Jeder Mock-Exporter nutzt dieselben Metriknamen wie sein echtes Vorbild - **ohne Garantie**,
damit exakt die Panel-Queries der jeweiligen (noch ungesehenen) Grafana.com-Dashboards zu
treffen, siehe die Docstrings in `mock-exporters/*.py` für den genauen Vorbehalt. Später auf
echte Daten umstellen: den jeweiligen Mock-Service in `docker-compose.yml` durch den echten
Exporter (siehe Tabelle) ersetzen und in `prometheus/prometheus.yml` das Scrape-Target
anpassen - an den Dashboards selbst ändert sich nichts.

## Schnellstart – Beispieldaten lokal ansehen

```bash
cd grafana-dashboards
cp .env.example .env
./fetch-community-dashboards.sh   # siehe Hinweis unten - braucht echten Internetzugang
docker compose up -d
```

Grafana danach unter `http://localhost:3000` (Login aus `.env`, Standard `admin` /
`change-me-please` - **vor produktivem Einsatz ändern**). Ordner "IT Infra Ops" enthält alle
vier Dashboards, sobald Schritt 2 (Dashboard-JSONs holen) einmal gelaufen ist.

`docker compose config -q` wurde in dieser Sandbox erfolgreich gegen die Compose-Datei
geprüft (Syntax valide) - ein echter `docker compose up` konnte hier nicht laufen (kein
Docker-Daemon in dieser Sandbox verfügbar, nur die CLI) und ist daher **nicht** end-to-end
gegen echte Container verifiziert.

## Setup in drei Schritten (für echte Infra statt/zusätzlich zu den Beispieldaten)

1. **Exporter auf den Zielsystemen installieren** (siehe Tabelle unten je Rolle) und in
   Prometheus eintragen - fertige Scrape-Config-Snippets liegen in
   [`prometheus-scrape-configs.yml`](prometheus-scrape-configs.yml), einfach in eure
   bestehende `prometheus.yml` unter `scrape_configs:` einfügen (oder, wenn ihr den
   Compose-Stack oben nutzt: `prometheus/prometheus.yml` direkt anpassen und die
   entsprechenden Mock-Exporter-Services aus `docker-compose.yml` entfernen).
2. **Dashboard-JSONs holen** – `grafana.com` ist aus dieser (Claude-Code-)Sandbox heraus per
   Egress-Policy blockiert, deshalb liegen hier keine fertigen JSON-Dateien bei. Von einer
   Maschine mit normalem Internetzugang einmalig:
   ```bash
   cd grafana-dashboards
   ./fetch-community-dashboards.sh
   ```
   Das lädt die JSONs nach `dashboards/` (danach committen, damit sie mit ins Repo
   wandern) – **oder** einfach manuell über Grafana → Dashboards → New → Import → ID/URL
   eingeben, ganz ohne dieses Repo.
3. **In Grafana laden** – entweder über das Import-Feld (Schritt 2, Alternative), oder
   file-basiert automatisch via [`provisioning/`](provisioning/) (siehe unten).

## Je Rolle im Detail

### DB-Admins – MS SQL Server

- **Dashboard:** "MS SQL Server Performance Dashboard" – auf grafana.com unter Data Source
  "Prometheus" + Suchbegriff "MSSQL"/"SQL Server" suchen und die aktuell bestbewertete
  Variante nehmen. In `fetch-community-dashboards.sh` ist **ID 9159** hinterlegt (zum
  Zeitpunkt der Erstellung dieser Datei ein verbreitetes SQL-Server-Dashboard für
  `sql_exporter`) – **vor dem ersten Einsatz auf grafana.com verifizieren**, dass die ID noch
  aktuell/nicht durch eine neuere Version abgelöst ist.
- **Exporter:** [`sql_exporter`](https://github.com/burningalchemist/sql_exporter) (aktiv
  gepflegter Fork) – generischer SQL-Exporter, der eure eigenen T-SQL-Queries ausführt.
  Braucht eine Collector-Config (YAML) mit den Queries für die "Best Practices"-Kennzahlen
  (Wait Stats, Buffer Cache Hit Ratio, Page Life Expectancy, Blocking, Deadlocks,
  Log-/Datendatei-Auslastung, ...) – Beispiel-Collector-Configs liegen im Exporter-Repo
  selbst (`examples/`). Port: `9399` (Standard).
  Least-Privilege-SQL-Login mit `VIEW SERVER STATE` reicht für die meisten Standard-Queries.

### Webserver-Admins – Apache2

- **Dashboard:** "Apache" – Suche auf grafana.com nach "Apache" + Data-Source Prometheus.
  In `fetch-community-dashboards.sh` ist **ID 3894** hinterlegt – ebenfalls vor Erstnutzung
  verifizieren.
- **Exporter:** [`apache_exporter`](https://github.com/Lusitaniae/apache_exporter) – liest
  Apaches eigenes `mod_status`-Modul (`/server-status?auto`, muss aktiviert und für den
  Exporter erreichbar sein, i. d. R. nur lokal/intern). Port: `9117` (Standard). Metriken
  u. a. `apache_up`, `apache_workers`, `apache_scoreboard`, `apache_accesses_total`,
  `apache_cpuload`.

### Systemadmins – Node Exporter Full (Server/VMs)

- **Dashboard:** ["Node Exporter Full"](https://grafana.com/grafana/dashboards/1860) von
  rfmoz – **ID 1860**, eines der bekanntesten und am meisten genutzten Community-Dashboards
  überhaupt, seit Jahren stabil unter dieser ID.
- **Exporter:** [`node_exporter`](https://github.com/prometheus/node_exporter) – offizieller
  Prometheus-Exporter, auf jedem zu überwachenden Linux/Unix-Host installiert (Standard-Port
  `9100`). Deckt CPU, Memory, Disk-I/O, Filesystem, Netzwerk, Load, systemd-Units u. v. m. ab.

### Systemadmins – VMware Host (ESXi/vCenter)

- **Dashboard:** Suche auf grafana.com nach "VMware vSphere" + Data-Source Prometheus - hier
  bewusst **keine ID fest hinterlegt**, da mehrere aktiv gepflegte Varianten kursieren und
  eine veraltete/falsche ID mehr schaden als eine kurze manuelle Suche.
- **Exporter:** z. B. [`vmware_exporter`](https://github.com/pryorda/vmware_exporter) (oder
  ein aktiv gepflegter Fork) – spricht die vSphere-API von ESXi/vCenter direkt an (eigener
  Read-Only-Service-Account, kein Agent auf den Gäste-VMs nötig). Standard-Port `9272`.
  Deckt Host-CPU/Memory/Storage/Netzwerk auf Hypervisor-Ebene ab - ergänzt Node Exporter
  Full (Gast-OS-Sicht) um die Host-Sicht.

## Provisioning in eine andere, bereits laufende Grafana-Instanz einbinden

Der Schnellstart oben bringt seine eigene Grafana mit (`docker-compose.yml`). Wollt ihr die
Dashboards stattdessen in eine schon existierende Grafana-Instanz einhängen, folgen
[`provisioning/dashboards/dashboards.yml`](provisioning/dashboards/dashboards.yml) +
[`provisioning/datasources/datasource.yml`](provisioning/datasources/datasource.yml)
demselben file-basierten Muster wie `demo-cert-monitoring/` - dort z. B. so einbinden:

```yaml
volumes:
  - ./grafana-dashboards/provisioning:/etc/grafana/provisioning:ro
  - ./grafana-dashboards/dashboards:/var/lib/grafana/dashboards:ro
```

`datasource.yml` zeigt auf `http://prometheus:9090` - Namen/URL an eure echte
Prometheus-Instanz anpassen, falls sie anders heißt/erreichbar ist.
