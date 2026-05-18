# M365 Service Status

> Lightweight status page for Microsoft 365 — built with FastAPI, runs in Docker, secured via Entra ID.

🇩🇪 [Deutsche Version](README.md) · 🇬🇧 **English**

[![CI](https://github.com/nic2045/My-M365-Statuspage/actions/workflows/ci.yml/badge.svg)](https://github.com/nic2045/My-M365-Statuspage/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com)
[![Security Audit](https://img.shields.io/badge/Security-pip--audit-4CAF50?logo=python&logoColor=white)](https://github.com/nic2045/My-M365-Statuspage/actions/workflows/ci.yml)
[![Dependabot](https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white)](https://github.com/nic2045/My-M365-Statuspage/network/updates)

---

## What is this?

The **M365 Service Status** page polls the [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/api/resources/servicehealth-overview) every 10 minutes and displays:

- The **current status** of monitored M365 services (Exchange, Teams, SharePoint, ...)
- A **90-day uptime bar** per service
- **Active incidents** with a chronological update history straight from Microsoft
- An **embeddable widget** for Typo3, Confluence DC or intranets

Access is secured via **Entra ID OIDC** — only internal users of your tenant can sign in.

The UI is **bilingual (German / English)** and auto-detects the language from the visitor's browser on the first visit. Admins can set a default language under *Settings → Language*; individual users can switch via the DE/EN toggle in the top bar.

---

## Features

| Feature | Details |
|---------|---------|
| **90-day history** | Coloured day bars (green / amber / red / grey) per service |
| **Incident timeline** | Active incidents with all Microsoft updates |
| **Auto-polling** | APScheduler polls the Graph API every 10 minutes |
| **OIDC login** | Entra ID – no separate user management needed |
| **Embed widget** | `/embed?token=KEY` – iframe-friendly, no X-Frame-Options |
| **Dark mode** | Light theme by default, dark mode via toggle |
| **Bilingual UI** | German + English, browser-locale aware, per-visitor cookie |
| **Extensible** | Add services via env var – no code changes |
| **Secure** | Non-root Docker container, WAL-mode SQLite, HTML sanitisation |

---

## Quickstart

### 1. Clone the repository and create the configuration

```bash
git clone https://github.com/nic2045/My-M365-Statuspage.git
cd My-M365-Statuspage
cp .env.example .env
```

### 2. Fill in `.env`

```dotenv
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-client-secret
AZURE_REDIRECT_URI=https://statuspage.example.com/auth/callback

# Leave empty: a fresh key is generated on first start and persisted to
# data/secret_key. To set your own (optional):
# python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=

EMBED_API_KEY=a-long-random-string  # leave empty = OIDC required
MONITORED_SERVICES=Exchange Online,SharePoint Online,Microsoft Teams
```

### 3. Start with Docker Compose

```bash
docker compose up -d --build
```

The page is then reachable at **`http://localhost:8000`**.
On first visit you will be redirected to Entra ID.

---

## Entra ID app registration

1. **Azure Portal → Entra ID → App registrations → New registration**
2. **Redirect URI** (type: web): `https://<your-domain>/auth/callback`
3. **API permissions → Add → Microsoft Graph → Application permissions:**
   - `ServiceHealth.Read.All`
4. **Grant admin consent** (required for application permissions)
5. **Certificates & secrets → New client secret** → put the value into `.env`

> A single app registration covers both: OIDC sign-in for browser users **and** Graph API access via client credentials.

---

## Configuration reference

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_TENANT_ID` | Directory (tenant) ID | — |
| `AZURE_CLIENT_ID` | Application (client) ID | — |
| `AZURE_CLIENT_SECRET` | Client secret | — |
| `AZURE_REDIRECT_URI` | OAuth callback URL | `http://localhost:8000/auth/callback` |
| `SECRET_KEY` | Session signing key (≥32 byte hex). Empty = auto-generated on first start, persisted to `data/secret_key` | *(auto)* |
| `EMBED_API_KEY` | Token for widget access without login | *(empty)* |
| `DATABASE_URL` | SQLAlchemy async URL | `sqlite+aiosqlite:///./data/statuspage.db` |
| `MONITORED_SERVICES` | Comma-separated service names (must match Graph API names exactly) | Exchange Online, SharePoint Online, Microsoft Teams |
| `POLL_INTERVAL_MINUTES` | Polling interval in minutes | `10` |
| `DEFAULT_LANGUAGE` | Fallback UI language when no cookie / Accept-Language match. Supported: `de`, `en` | `de` |
| `DEBUG` | Enables `/api/docs` and verbose logging | `false` |

**Supported `MONITORED_SERVICES` values** (must match the Graph API names exactly):

`Exchange Online` · `SharePoint Online` · `Microsoft Teams` · `Microsoft Intune` · `Azure Active Directory` · `OneDrive for Business` · `Microsoft 365 suite` · `Power BI` · `Yammer Enterprise` · `Dynamics 365 Apps`

---

## Deployment (production)

```bash
# Build the image and start the container
docker compose up -d --build

# Tail the logs
docker compose logs -f statuspage

# Health check
curl http://localhost:8000/api/v1/health
# → {"status":"ok"}

# Restart the container (after .env changes)
docker compose restart statuspage
```

The SQLite database lives in the named Docker volume **`statuspage_data`** and survives container restarts.

### Behind a reverse proxy (nginx / Traefik)

```nginx
location / {
    proxy_pass         http://127.0.0.1:8000;
    proxy_set_header   Host $host;
    proxy_set_header   X-Forwarded-Proto https;   # important for secure session cookies
    proxy_set_header   X-Real-IP $remote_addr;
}
```

> Make sure `AZURE_REDIRECT_URI` points to the public HTTPS URL and `DEBUG=false` is set.

---

## Embedding into Typo3 / Confluence DC

Set an `EMBED_API_KEY` in `.env` — the token replaces the OIDC login for the widget:

```dotenv
EMBED_API_KEY=a-long-random-string-here
```

### iframe snippet (Typo3 HTML element, Confluence HTML macro)

```html
<iframe
  src="https://statuspage.example.com/embed?token=YOUR_EMBED_KEY"
  width="100%"
  height="180"
  frameborder="0"
  scrolling="no"
  style="border: none; overflow: hidden;"
  title="M365 Service Status">
</iframe>
```

### JavaScript snippet (dynamic embed)

```html
<div id="m365-status-widget"></div>
<script>
(function () {
  var f = document.createElement('iframe');
  f.src = 'https://statuspage.example.com/embed?token=YOUR_EMBED_KEY';
  f.style.cssText = 'width:100%;height:180px;border:none;overflow:hidden;';
  f.scrolling = 'no';
  f.title = 'M365 Service Status';
  document.getElementById('m365-status-widget').appendChild(f);
})();
</script>
```

> **Security note:** The embed key only grants read-only access to the current service status — no user data. Use a long, random string.

---

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env
cp .env.example .env   # fill in the values

# Start the server (with auto-reload)
uvicorn app.main:app --reload --port 8000

# Run the linter
pip install ruff
ruff check app/
```

Or with Docker (the override is picked up automatically):

```bash
docker compose up --build   # sets DEBUG=true and --reload
```

---

## Architecture

```
FastAPI (app/main.py)
├── SessionMiddleware  ──  Entra ID OIDC (authlib)
├── LanguageMiddleware ──  cookie / Accept-Language → ContextVar
├── Routers
│   ├── /                  Public status page (OIDC protected)
│   ├── /embed             Embeddable widget (token or OIDC)
│   ├── /auth/*            Login · callback · logout
│   ├── /lang/{code}       Persist UI language choice
│   └── /api/v1/*          JSON API · health check
├── Jinja2 templates (Tailwind CSS Play CDN)
│   ├── base.html          Nav, language switcher, dark-mode toggle
│   ├── status.html        Main page
│   ├── embed.html         Widget (standalone)
│   └── partials/          service_row · uptime_bar · incident_card
├── APScheduler ── every 10 min ──► Microsoft Graph API (MSAL)
│   ├── /serviceAnnouncement/healthOverviews   (service status)
│   └── /serviceAnnouncement/issues            (active incidents)
└── SQLite  (SQLAlchemy async + aiosqlite, WAL mode)
    ├── service_status     Per-day status per service (90-day history)
    ├── incidents          Active and resolved incidents
    └── incident_updates   Update timeline per incident
```

---

## Severity colour reference

All coloured chips, dots, borders and bars go through central helpers in `app/templates.py` and `app/models.py` — no hardcoded Tailwind classes inside templates. Palette tweaks happen in a single place.

| Dimension | Values | Colour family |
|-----------|--------|---------------|
| Service status | `operational` · `degraded` · `interrupted` · `unknown` | green · amber · red · grey |
| Incident severity | `critical` · `high` · `medium` · `low` | red · orange · amber · blue |
| Incident phase | `active` · `acknowledged` · `monitoring` · `resolved` | yellow · orange · blue · emerald |
| Incident type | `incident` · `advisory` · `maintenance` | red · amber · blue |

Active phases (`active`/`acknowledged`/`monitoring`/`in_progress`) and non-operational service statuses (`degraded`/`interrupted`) pulse via `animate-pulse` — automatically suppressed under `prefers-reduced-motion: reduce`. All helpers ship with `dark:` variants; contrasts are WCAG AA-checked against the respective background class.

---

## CI / CD

| Job | Description |
|-----|-------------|
| **Syntax & Imports** | `py_compile` + app import + DB init |
| **Ruff Lint** | Code quality and import ordering |
| **Security Audit** | `pip-audit` against known CVEs |
| **Trivy Image Scan** | Docker image scanned for OS / library CVEs |
| **Weekly Audit** | Monday-morning security scan, opens an issue on findings |
| **Release workflow** | Tag `v*.*.*` → GHCR push (multi-arch) → GitHub release |
