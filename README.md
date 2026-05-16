# M365 Dienststatus

Leichtgewichtige FastAPI-Statusseite für Microsoft 365-Dienste. Abfragt alle 10 Minuten die Microsoft Graph API, speichert Verlaufsdaten in SQLite und zeigt aktive Incidents mit vollständigem Update-Verlauf an. Abgesichert über Entra ID (OIDC).

## Features

- **90-Tage Verfügbarkeitsbalken** pro Dienst
- **Aktive Incidents** mit chronologischem Update-Verlauf aus der Graph API
- **Automatische Abfrage** alle 10 Minuten (APScheduler)
- **Entra ID OIDC** – nur interne Benutzer erhalten Zugang
- **Einbettungs-Widget** (`/embed`) für Typo3, Confluence DC und andere Portale
- **Helles Design** mit optionalem Dark Mode (Tailwind CSS)
- **Erweiterbar**: neue M365-Dienste nur per Umgebungsvariable hinzufügen

---

## Voraussetzungen

### Azure App-Registrierung

1. Im Azure Portal unter **Entra ID → App-Registrierungen** eine neue App anlegen
2. **Redirect-URI** hinzufügen (Typ: Web): `https://<deine-domain>/auth/callback`
3. **API-Berechtigungen** → Berechtigung hinzufügen → Microsoft Graph → Anwendungsberechtigungen:
   - `ServiceHealth.Read.All` ✓
4. **Administrator-Zustimmung erteilen** (für die Anwendungsberechtigung erforderlich)
5. **Zertifikate & Geheimnisse** → Neues Clientgeheimnis → Wert kopieren

> Dieselbe App-Registrierung wird für den OIDC-Login (Benutzer) **und** den Graph-API-Zugriff (Client Credentials) verwendet.

---

## Konfiguration

```bash
cp .env.example .env
# .env mit echten Werten befüllen
```

| Variable | Beschreibung | Beispiel |
|----------|-------------|---------|
| `AZURE_TENANT_ID` | Verzeichnis-ID (Tenant) | `xxxxxxxx-xxxx-...` |
| `AZURE_CLIENT_ID` | Anwendungs-ID (Client) | `xxxxxxxx-xxxx-...` |
| `AZURE_CLIENT_SECRET` | Clientgeheimnis | `abc123~...` |
| `AZURE_REDIRECT_URI` | Callback-URL | `https://statuspage.example.com/auth/callback` |
| `SECRET_KEY` | Session-Schlüssel (≥32 Byte) | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `EMBED_API_KEY` | API-Key für Widget (leer = OIDC) | `abc123...` |
| `MONITORED_SERVICES` | Überwachte Dienste | `Exchange Online,SharePoint Online,Microsoft Teams` |
| `POLL_INTERVAL_MINUTES` | Abfrageintervall | `10` |
| `DEBUG` | Debug-Modus | `false` |

**Unterstützte Graph API Service-Namen** (für `MONITORED_SERVICES`):
- `Exchange Online`
- `SharePoint Online`
- `Microsoft Teams`
- `Microsoft Intune`
- `Azure Active Directory`
- `OneDrive for Business`
- `Microsoft 365 suite`
- `Yammer Enterprise`
- `Power BI`
- `Dynamics 365 Apps`

---

## Deployment (Docker)

```bash
# Produktiv
docker compose up -d --build

# Status prüfen
docker compose ps
docker compose logs -f statuspage

# Gesundheitscheck
curl http://localhost:8000/api/v1/health
```

Die SQLite-Datenbank wird im Docker Volume `statuspage_data` persistiert.

### Hinter einem Reverse Proxy (nginx / Traefik)

Der Container lauscht auf Port `8000`. Stelle sicher, dass:
- TLS-Terminierung im Proxy erfolgt
- `X-Forwarded-Proto: https` weitergeleitet wird (für sichere Session-Cookies)
- Die Redirect-URI in Entra ID mit der öffentlichen HTTPS-URL übereinstimmt

---

## Entwicklung

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# .env anlegen
cp .env.example .env  # Werte eintragen

# Starten (mit Auto-Reload)
uvicorn app.main:app --reload --port 8000
```

Oder mit Docker (Override wird automatisch angewendet):

```bash
docker compose up --build
```

---

## Einbettung in Typo3 / Confluence DC

### Voraussetzung

Einen `EMBED_API_KEY` in `.env` setzen (leer lassen = OIDC-Session erforderlich):

```dotenv
EMBED_API_KEY=ein-langer-zufaelliger-string-hier
```

### iframe-Snippet (Typo3 HTML-Inhaltselement, Confluence HTML-Makro)

```html
<iframe
  src="https://statuspage.example.com/embed?token=DEIN_EMBED_KEY"
  width="440"
  height="160"
  frameborder="0"
  scrolling="no"
  style="border: none; overflow: hidden; width: 100%;"
  title="M365 Dienststatus">
</iframe>
```

### JavaScript-Snippet für Confluence DC HTML-Makro

```html
<div id="m365-status-widget"></div>
<script>
(function () {
  var f = document.createElement('iframe');
  f.src = 'https://statuspage.example.com/embed?token=DEIN_EMBED_KEY';
  f.style.cssText = 'width:100%;height:160px;border:none;overflow:hidden;';
  f.scrolling = 'no';
  f.title = 'M365 Dienststatus';
  document.getElementById('m365-status-widget').appendChild(f);
})();
</script>
```

> **Sicherheitshinweis**: Der Embed-Key gibt Lesezugriff auf den aktuellen Dienststatus – keine Benutzerdaten. Verwende einen langen, zufälligen String und gib ihn nicht öffentlich weiter.

---

## Neue Dienste hinzufügen

Nur die `.env` anpassen (kein Code-Change erforderlich):

```dotenv
MONITORED_SERVICES=Exchange Online,SharePoint Online,Microsoft Teams,Microsoft Intune
```

Container neu starten – der neue Dienst erscheint sofort in der Statusseite.

---

## Architektur

```
FastAPI (main.py)
├── OIDC Auth (authlib + SessionMiddleware)
├── Routers: /, /embed, /auth/*, /api/v1/*
├── Jinja2 Templates (Tailwind CSS Play CDN)
│   ├── base.html (Nav, Dark Mode Toggle)
│   ├── status.html (Hauptseite)
│   ├── embed.html (Widget)
│   └── partials/ (service_row, uptime_bar, incident_card)
├── APScheduler (poll alle 10 min)
│   └── Graph API (MSAL Client Credentials + httpx)
└── SQLite via SQLAlchemy async + aiosqlite
    ├── ServiceStatus (90-Tage-Verlauf)
    ├── Incident (aktive/behobene Störungen)
    └── IncidentUpdate (Update-Timeline)
```
