# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Commands

All commands run via `make` (see `Makefile`):

```bash
make dev          # Start FastAPI dev server (uvicorn --reload) on localhost:8000
make install      # Install dependencies (uv sync + npm install)
make docker       # Build & start full Docker Compose environment
make test         # Run pytest on tests/
make lint         # Run ruff linter (check mode)
make stop         # Stop Docker containers
make shell        # Open bash in running container
make css          # Compile Tailwind CSS to static/css/app.css
```

**Single test:** `uv run pytest tests/test_file.py::test_function -v`

**Lint fix:** `uv run ruff check . --fix`

## Architecture Overview

**M365 Statuspage** is a lightweight status dashboard for Microsoft 365 services. It polls Microsoft Graph Health API every 10 minutes, tracks incident lifecycle, and exposes a public status page + embeddable widget.

### High-Level Flow

1. **Scheduler** (`app/scheduler.py`): APScheduler runs `poll_graph_api()` every 10 minutes
   - Fetches health overviews (daily service status: operational/degraded/interrupted)
   - Fetches active incidents (ongoing problems with titles, status, updates)
   - Fetches recently resolved incidents (last 30 days, for uptime calculation)
   - Syncs each as `Incident` + `IncidentUpdate` records
   - Publishes auto-generated updates when incidents resolve (Microsoft's closing posts)
   - Dispatches notifications (email + Teams webhooks) only for real incidents (`classification: incident`)

2. **Database** (`app/models.py`): SQLite (async via aiosqlite) with 6 tables
   - `service_status`: Daily snapshots (one row per service per day) for 90-day uptime bars
   - `incidents`: Synced from Graph API, grouped by `graph_issue_id`; manual edits override Graph text (translations, admin notes)
   - `incident_updates`: Chronological posts from Microsoft or admin; `is_published` gates visibility on public page
   - `monitored_services`: Toggle which services to track; `is_enabled` controls polling
   - `subscribers`: Email/Teams webhooks; per-service subscription lists
   - `app_settings`: KV store for runtime config (SMTP, OpenBao token, etc.)

3. **Web Routes** (`app/routers/`)
   - `status.py`: Public status page + 90-day history (template rendering)
   - `admin.py`: OIDC-gated admin panel (toggle services, translate incidents, publish queued updates, manage subscribers)
   - `embed.py`: Iframe-safe widget endpoint `/embed?token=KEY` (no login required if `EMBED_API_KEY` set)
   - `api.py`: JSON endpoints for status, incidents, health
   - `auth_router.py`: Entra ID OIDC login/logout
   - `subscribers.py`: Public email subscription + confirmation flow

4. **Authentication** (`app/auth.py`): Entra ID OIDC + optional role-based access
   - Every route checks `LoginRequired` dependency (unless explicitly skipped for embed/public)
   - Admin area (`/admin`) requires `ADMIN_ROLE` claim (default: "Admin") or email in `ADMIN_EMAILS`
   - Session stored server-side (Starlette middleware, signed cookie references DB)

5. **Notifications** (`app/notifications.py`): Async tasks dispatched after DB commit
   - Email via aiosmtplib (SMTP config from `app_settings` table)
   - Microsoft Teams webhooks (per-subscriber `teams_webhook_url`)
   - Only fires for new incidents or status transitions; historical backfills suppressed
   - Uses i18n labels for subject/body (`app/i18n.py`)

### Key Design Patterns

**Sync vs. Notify:** Scheduler commits incidents to DB **first**, then dispatches notifications. This ensures:
- Subscribers never see a notification for an incident that was rolled back
- Notifications contain accurate incident IDs + links
- See `scheduler.py` lines 279–334 for this three-phase approach (health overviews → active incidents → resolved incidents, each in separate transaction)

**Translation Lifecycle:** When an admin translates an incident via `/admin/incidents/{id}/translate`:
- Sets `incident.translated_lang` to the language code (e.g., "de")
- Scheduler stops overwriting `title` from Graph's English text on subsequent polls
- Admin notes in `description` are preserved (only synced on first import if empty)
- See `scheduler.py` lines 179–184 for this gate

**State Change Timeline:** Each incident tracks phase progression (Investigating → Identified → Monitoring → Resolved):
- `IncidentUpdate` records with `update_type: "state_change"` mark phase transitions
- Generated when incident status changes between polls (graph.py maps Graph statuses to internal phases)
- New incidents synced as already-resolved also get a state_change entry (for historical completeness)
- Public detail page renders these as a phase bar timeline
- See `scheduler.py` lines 190–196 for this logic

**Publish Gate:** Microsoft's posts arrive as unpublished (`is_published: false`). Admin must review before they appear:
- Exception: posts on already-resolved incidents auto-publish (they're the resolution explanation)
- See `scheduler.py` line 204 for this auto-publish logic

## Data Model

**Incidents** have:
- `classification`: "incident" (real outage) | "advisory" (informational) | "maintenance" (scheduled work)
- `status`: "active" | "acknowledged" | "monitoring" | "resolved" (internal phases, mapped from Graph statuses)
- `source`: "graph" (auto-synced) or "manual" (admin-created)
- `severity`: "critical" | "high" | "medium" | "low" (from Graph for incidents, empty for maintenance)

**Services** are toggled via `MonitoredServices.is_enabled`. The uptime bar calculation (`get_uptime_bars()` in `crud.py`) runs live from:
1. Last 30 days of `Incident` records in the DB
2. Daily `ServiceStatus` snapshots (one per day per service)
3. Falls back to operational if no data for a day (assumes healthy if we saw nothing)

**Subscribers** track:
- `channel`: "email" (default) or "teams" (posts to webhook instead of email)
- `services`: NULL/empty = all services; comma-separated list = filtered
- Notifications dispatch only to subscribed services

## Testing

- **Location:** `tests/` directory
- **Framework:** pytest + pytest-asyncio
- **Run:** `make test` or `uv run pytest tests/ -v`
- **Async fixtures:** Use `@pytest.mark.asyncio` + async test functions
- **DB:** Tests use temporary SQLite (no teardown needed between tests due to async isolation)

## i18n (Internationalization)

All user-facing strings are in `app/i18n.py`:
- `LABELS`: Dict of `{label_key: {language: text}}`
- `LABELS_BY_LANG`: Inverted index for faster lookups by lang
- `set_current_language()` / `get_current_language()`: Thread-local context
- Templates use `{{ LABELS["key"][current_lang] }}`
- See `README.md` for supported languages (German + English)

## Frontend

- **Templates:** Jinja2 in `templates/` (base.html extends to status.html, admin.html, etc.)
- **Styles:** Tailwind CSS (compiled to `static/css/app.css` via npm, not CDN)
  - Status badge colors: `STATUS_BADGE_CLASSES` in `models.py`
  - Uptime bar colors: `STATUS_TAILWIND_BAR` in `models.py`
- **Dark mode:** Toggle in UI, persisted to `lang` cookie
- **Severity badges:** Use `severity_badge(severity)` macro in `templates/partials/_icons.html`

## Windows Development

On Windows 10/11, use `Start.ps1` + `setup-wsl2.ps1` for one-click setup:
- **VS Code:** Terminal automatically runs `Start.ps1`, which detects WSL2/Docker or prompts to run setup
- **Manual:** Open PowerShell (Admin) and run `.\setup-wsl2.ps1` or double-click `setup-wsl2.bat`
- See `WINDOWS-SETUP.md` for full guide + troubleshooting

## Configuration

See `.env.example` for all env vars. Key ones:

- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`: Entra ID OAuth (app registration required in Azure Portal)
- `MONITORED_SERVICES`: Comma-separated service names to track (must match Graph API names exactly)
- `POLL_INTERVAL_MINUTES`: How often to check Graph API (default: 10)
- `DEBUG`: Enable `/api/docs` Swagger UI + verbose logging
- `ADMIN_ROLE`: App role claim name for `/admin` access (default: "Admin")
- `ADMIN_EMAILS`: Optional email allowlist (OIDC UPN claim)
- `EMBED_API_KEY`: Token for public widget access (iframe-safe, no login needed)
- `OPENBAO_*`: Optional secret rotation via Vault-like service (see README for details)
- `DISABLE_AUTH`: Disable OIDC entirely (development only, never production)

## Common Tasks

**Add a new monitored service:** Set `MONITORED_SERVICES=...,New Service,...` in `.env`. Graph API polls it on next cycle. Admin panel shows it to toggle on/off.

**Create a manual incident:** Admin → Create Incident form. Sets `source: "manual"`, skips Graph sync. Title/description are admin-authored.

**Debug a failing poll:** Check logs (`make logs` in Docker). `app/graph_client.py` fetches from Microsoft Graph; `scheduler.py` syncs to DB. Add print statements or use Python debugger (`.vscode/launch.json` has attach config).

**Translate an incident:** Admin → Incidents table → Click incident → "Translate" → Select language → Paste translation. Sets `translated_lang`, stops Graph overwrites.

**Change SMTP settings:** Admin → Settings → Email Config. Saves to `app_settings` table. Notifications use these on next send.

## Code Style

- **Linter:** ruff (configured in `ruff.toml`)
- **Async:** Use `async`/`await` throughout; FastAPI + SQLAlchemy are async-native
- **Errors:** FastAPI raises `HTTPException(status_code, detail)` for HTTP errors
- **Logging:** Use `logging.getLogger(__name__)` per module; log levels DEBUG (dev), INFO (normal), ERROR (problems)
- **Secrets:** Never commit `.env` files; use `.env.example` as template

## Recent Changes & PR Context

The latest PRs added:
- **#184**: Severity display in incident cards + state-change recording for new resolved incidents
- **#185**: Windows WSL2 Docker setup automation (setup-wsl2.ps1, setup-wsl2.bat) + VS Code integration (Start.ps1, .vscode/ config)

Check PR descriptions for context on why specific changes were made (e.g., why state_change is recorded for new incidents that are already resolved = they need a timeline marker).
