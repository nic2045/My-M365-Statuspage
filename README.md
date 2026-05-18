# M365 Dienststatus

> Leichtgewichtige Statusseite für Microsoft 365 — gebaut mit FastAPI, betrieben in Docker, abgesichert via Entra ID.

🇩🇪 **Deutsch** · 🇬🇧 [English version](README.en.md)

[![CI](https://github.com/nic2045/My-M365-Statuspage/actions/workflows/ci.yml/badge.svg)](https://github.com/nic2045/My-M365-Statuspage/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com)
[![Security Audit](https://img.shields.io/badge/Security-pip--audit-4CAF50?logo=python&logoColor=white)](https://github.com/nic2045/My-M365-Statuspage/actions/workflows/ci.yml)
[![Dependabot](https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white)](https://github.com/nic2045/My-M365-Statuspage/network/updates)

---

## Was ist das?

Die **M365 Dienststatus**-Seite fragt alle 10 Minuten die [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/api/resources/servicehealth-overview) ab und zeigt:

- Den **aktuellen Status** überwachter M365-Dienste (Exchange, Teams, SharePoint, ...)
- Einen **90-Tage-Verfügbarkeitsbalken** pro Dienst
- **Aktive Incidents** mit chronologischem Update-Verlauf direkt aus Microsoft
- Ein **einbettbares Widget** für Typo3, Confluence DC oder Intranets

Der Zugang ist per **Entra ID OIDC** gesichert — nur interne Benutzer deines Tenants können sich einloggen.

---

## Features

| Feature | Details |
|---------|---------|
| **90-Tage-Verlauf** | Farbige Tagesbalken (grün / gelb / rot / grau) pro Dienst |
| **Incident-Timeline** | Aktive Störungen mit allen Microsoft-Updates |
| **Auto-Polling** | APScheduler fragt die Graph API alle 10 Minuten ab |
| **OIDC-Login** | Entra ID – kein eigenes User-Management nötig |
| **Embed-Widget** | `/embed?token=KEY` – iframe-tauglich ohne X-Frame-Options |
| **Dark Mode** | Helles Design als Standard, Dark Mode per Toggle |
| **Erweiterbar** | Neue Dienste nur per Umgebungsvariable, kein Code-Change |
| **Sicher** | Non-root Docker-Container, WAL-SQLite, HTML-Sanitierung |

---

## Schnellstart

### 1. Repository klonen & Konfiguration anlegen

```bash
git clone https://github.com/nic2045/My-M365-Statuspage.git
cd My-M365-Statuspage
cp .env.example .env
```

### 2. `.env` befüllen

```dotenv
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=dein-client-secret
AZURE_REDIRECT_URI=https://statuspage.example.com/auth/callback

# Leer lassen: wird beim ersten Start automatisch generiert und unter
# data/secret_key persistiert. Eigenen Wert (optional) erzeugen mit:
# python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=

EMBED_API_KEY=ein-langer-zufaelliger-string  # leer lassen = OIDC erforderlich
MONITORED_SERVICES=Exchange Online,SharePoint Online,Microsoft Teams
```

### 3. Docker Compose starten

```bash
docker compose up -d --build
```

Die Seite ist anschließend unter **`http://localhost:8000`** erreichbar.  
Beim ersten Aufruf wird man zu Entra ID weitergeleitet.

---

## Entra ID App-Registrierung

1. **Azure Portal → Entra ID → App-Registrierungen → Neue Registrierung**
2. **Redirect-URI** (Typ: Web): `https://<deine-domain>/auth/callback`
3. **API-Berechtigungen → Hinzufügen → Microsoft Graph → Anwendungsberechtigungen:**
   - `ServiceHealth.Read.All`
4. **Administrator-Zustimmung erteilen** (für Anwendungsberechtigungen Pflicht)
5. **Zertifikate & Geheimnisse → Neues Clientgeheimnis** → Wert in `.env` eintragen

> Eine App-Registrierung deckt beides ab: OIDC-Login für Browser-Benutzer **und** den Graph-API-Zugriff per Client Credentials.

---

## Konfigurationsreferenz

| Variable | Beschreibung | Standard |
|----------|-------------|---------|
| `AZURE_TENANT_ID` | Verzeichnis-ID (Tenant) | — |
| `AZURE_CLIENT_ID` | Anwendungs-ID | — |
| `AZURE_CLIENT_SECRET` | Clientgeheimnis | — |
| `AZURE_REDIRECT_URI` | OAuth-Callback-URL | `http://localhost:8000/auth/callback` |
| `SECRET_KEY` | Session-Signaturschlüssel (≥32 Byte Hex). Leer = Auto-Generierung beim ersten Start, persistiert in `data/secret_key` | *(auto)* |
| `EMBED_API_KEY` | Token für Widget-Zugriff ohne Login | *(leer)* |
| `DATABASE_URL` | SQLAlchemy Async URL | `sqlite+aiosqlite:///./data/statuspage.db` |
| `MONITORED_SERVICES` | Kommagetrennte Dienstnamen (Graph API exakt) | Exchange Online, SharePoint Online, Microsoft Teams |
| `POLL_INTERVAL_MINUTES` | Abfrageintervall in Minuten | `10` |
| `DEBUG` | Aktiviert `/api/docs`, ausführliches Logging | `false` |

**Unterstützte `MONITORED_SERVICES`-Werte** (Graph API-Namen exakt einhalten):

`Exchange Online` · `SharePoint Online` · `Microsoft Teams` · `Microsoft Intune` · `Azure Active Directory` · `OneDrive for Business` · `Microsoft 365 suite` · `Power BI` · `Yammer Enterprise` · `Dynamics 365 Apps`

---

## Deployment (Produktion)

```bash
# Image bauen und Container starten
docker compose up -d --build

# Logs live anzeigen
docker compose logs -f statuspage

# Gesundheitscheck
curl http://localhost:8000/api/v1/health
# → {"status":"ok"}

# Container neustarten (nach .env-Änderung)
docker compose restart statuspage
```

Die SQLite-Datenbank liegt im benannten Docker Volume **`statuspage_data`** und überlebt Container-Neustarts.

### Hinter einem Reverse Proxy (nginx / Traefik)

```nginx
location / {
    proxy_pass         http://127.0.0.1:8000;
    proxy_set_header   Host $host;
    proxy_set_header   X-Forwarded-Proto https;   # wichtig für sichere Session-Cookies
    proxy_set_header   X-Real-IP $remote_addr;
}
```

> Stelle sicher, dass `AZURE_REDIRECT_URI` auf die öffentliche HTTPS-URL zeigt und `DEBUG=false` gesetzt ist.

---

## Einbettung in Typo3 / Confluence DC

Einen `EMBED_API_KEY` in `.env` setzen — der Token ersetzt den OIDC-Login für das Widget:

```dotenv
EMBED_API_KEY=ein-langer-zufaelliger-string-hier
```

### iframe-Snippet (Typo3 HTML-Element, Confluence HTML-Makro)

```html
<iframe
  src="https://statuspage.example.com/embed?token=DEIN_EMBED_KEY"
  width="100%"
  height="180"
  frameborder="0"
  scrolling="no"
  style="border: none; overflow: hidden;"
  title="M365 Dienststatus">
</iframe>
```

### JavaScript-Snippet (dynamisches Einbetten)

```html
<div id="m365-status-widget"></div>
<script>
(function () {
  var f = document.createElement('iframe');
  f.src = 'https://statuspage.example.com/embed?token=DEIN_EMBED_KEY';
  f.style.cssText = 'width:100%;height:180px;border:none;overflow:hidden;';
  f.scrolling = 'no';
  f.title = 'M365 Dienststatus';
  document.getElementById('m365-status-widget').appendChild(f);
})();
</script>
```

> **Sicherheitshinweis:** Der Embed-Key gewährt nur Lesezugriff auf den aktuellen Dienststatus — keine Benutzerdaten. Verwende einen langen, zufälligen String.

---

## Entwicklung

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# .env anlegen
cp .env.example .env   # Werte eintragen

# Server starten (mit Auto-Reload)
uvicorn app.main:app --reload --port 8000

# Linter ausführen
pip install ruff
ruff check app/
```

Oder mit Docker (der Override wird automatisch angewendet):

```bash
docker compose up --build   # setzt DEBUG=true und --reload
```

---

## Architektur

```
FastAPI (app/main.py)
├── SessionMiddleware  ──  Entra ID OIDC (authlib)
├── Routers
│   ├── /                  Hauptstatusseite (OIDC geschützt)
│   ├── /embed             Einbettbares Widget (Token oder OIDC)
│   ├── /auth/*            Login · Callback · Logout
│   └── /api/v1/*          JSON-API · Healthcheck
├── Jinja2-Templates (Tailwind CSS Play CDN)
│   ├── base.html          Nav, Dark-Mode-Toggle
│   ├── status.html        Hauptseite
│   ├── embed.html         Widget (standalone)
│   └── partials/          service_row · uptime_bar · incident_card
├── APScheduler ── alle 10 min ──► Microsoft Graph API (MSAL)
│   ├── /serviceAnnouncement/healthOverviews   (Dienststatus)
│   └── /serviceAnnouncement/issues            (Aktive Incidents)
└── SQLite  (SQLAlchemy async + aiosqlite, WAL-Modus)
    ├── service_status     Tagesstatus pro Dienst (90-Tage-Verlauf)
    ├── incidents          Aktive und behobene Störungen
    └── incident_updates   Update-Timeline pro Incident
```

---

## Severity Color Reference

Alle farbigen Chips, Dots, Borders und Balken laufen über zentrale Helper in `app/templates.py` und `app/models.py` — keine hartkodierten Tailwind-Klassen in Templates. Palette-Anpassungen passieren an einer Stelle.

| Dimension | Werte | Farbfamilie |
|-----------|-------|-------------|
| Service-Status | `operational` · `degraded` · `interrupted` · `unknown` | grün · amber · rot · grau |
| Incident-Severity | `critical` · `high` · `medium` · `low` | rot · orange · amber · blau |
| Incident-Phase | `active` · `acknowledged` · `monitoring` · `resolved` | gelb · orange · blau · emerald |
| Incident-Typ | `incident` · `advisory` · `maintenance` | rot · amber · blau |

Aktive Phasen (`active`/`acknowledged`/`monitoring`/`in_progress`) und nicht-operative Service-Status (`degraded`/`interrupted`) pulsieren via `animate-pulse` — automatisch unterdrückt unter `prefers-reduced-motion: reduce`. Alle Helper liefern `dark:`-Varianten mit; Kontraste sind WCAG AA gegen die jeweilige Hintergrundklasse geprüft.

---

## CI / CD

| Job | Beschreibung |
|-----|-------------|
| **Syntax & Imports** | `py_compile` + App-Import + DB-Init |
| **Ruff Lint** | Code-Qualität und Import-Sortierung |
| **Security Audit** | `pip-audit` gegen bekannte CVEs |
| **Trivy Image Scan** | Docker-Image auf OS- und Library-CVEs |
| **Wöchentlicher Audit** | Montags automatischer Sicherheitsscan, öffnet Issue bei Findings |
| **Release-Workflow** | Tag `v*.*.*` → GHCR-Push (multi-arch) → GitHub Release |
