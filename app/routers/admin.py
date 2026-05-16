import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import settings
from app.crud import (
    add_incident_post,
    add_state_change_entry,
    admin_update_incident,
    backfill_service_status_from_issues,
    create_manual_incident,
    ensure_service_known,
    get_all_incidents,
    get_all_monitored_services,
    get_enabled_services,
    get_incident_by_id,
    get_resolved_incidents,
    get_scheduled_maintenances,
    get_suppressed_incidents,
    set_service_enabled,
    set_service_status_manual,
    toggle_suppress_incident,
)
from app.database import AsyncSessionLocal
from app.dependencies import get_db
from app.graph_client import (
    fetch_active_issues,
    fetch_health_overviews,
    fetch_issues_since,
    fetch_recently_resolved_issues,
)
from app.models import MonitoredService
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _parse_form_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


async def _backfill_service(service_name: str) -> None:
    """Background task: fetch 90-day issue history and fill in missing status rows."""
    try:
        issues = await fetch_issues_since(service_name, days=90)
        async with AsyncSessionLocal() as db:
            await backfill_service_status_from_issues(db, service_name, issues, days=90)
            await db.commit()
        logger.info("Backfill completed for %s (%d issues)", service_name, len(issues))
    except Exception:
        logger.exception("Backfill failed for %s", service_name)


# Tracks a pending delayed poll so it can be cancelled and restarted when
# another service is enabled before the timer fires (debounce behaviour).
_pending_poll_task: asyncio.Task | None = None


async def _delayed_poll(delay: float = 8.0) -> None:
    """Wait N seconds, then run a full Graph API poll.

    Each call to schedule_delayed_poll() cancels any previous pending task
    so only one poll fires, 8 s after the *last* service toggle.
    """
    await asyncio.sleep(delay)
    try:
        from app.scheduler import poll_graph_api  # local import avoids circular dep
        await poll_graph_api()
        logger.info("Delayed poll completed after enabling service.")
    except asyncio.CancelledError:
        pass  # task was cancelled because another service was enabled
    except Exception:
        logger.exception("Delayed poll failed")


def _schedule_delayed_poll(delay: float = 8.0) -> None:
    """Cancel any pending delayed poll and start a fresh one."""
    global _pending_poll_task
    if _pending_poll_task and not _pending_poll_task.done():
        _pending_poll_task.cancel()
    _pending_poll_task = asyncio.create_task(_delayed_poll(delay))


@router.get("/")
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    incidents = await get_all_incidents(db, include_resolved=False)
    resolved = await get_resolved_incidents(db, limit=10)
    suppressed = await get_suppressed_incidents(db)
    maintenances = await get_scheduled_maintenances(db)
    enabled_services = await get_enabled_services(db)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": user,
            "incidents": incidents,
            "resolved_incidents": resolved,
            "suppressed_incidents": suppressed,
            "maintenances": maintenances,
            "services": enabled_services,
            "page_title": f"Admin – {settings.APP_TITLE}",
        },
    )


@router.get("/settings")
async def admin_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    all_services = await get_all_monitored_services(db)
    return templates.TemplateResponse(
        request,
        "admin/settings.html",
        {
            "user": user,
            "all_services": all_services,
            "page_title": f"Einstellungen – {settings.APP_TITLE}",
        },
    )


@router.get("/incidents/new")
async def new_incident_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    enabled_services = await get_enabled_services(db)
    return templates.TemplateResponse(
        request,
        "admin/incident_form.html",
        {
            "user": user,
            "services": enabled_services,
            "page_title": "Neue Störung / Hinweis",
        },
    )


@router.post("/incidents")
async def create_incident(
    title: Annotated[str, Form()],
    service_name: Annotated[str, Form()],
    classification: Annotated[str, Form()],
    severity: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    incident = await create_manual_incident(
        db,
        title=title,
        service_name=service_name,
        classification=classification,
        severity=severity or "",
        description=description or None,
    )
    await db.commit()
    return RedirectResponse(url=f"/admin/incidents/{incident.id}", status_code=303)


@router.get("/incidents/{incident_id}")
async def incident_detail(
    request: Request,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    incident = await get_incident_by_id(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    enabled_services = await get_enabled_services(db)
    return templates.TemplateResponse(
        request,
        "admin/incident_detail.html",
        {
            "user": user,
            "incident": incident,
            "services": enabled_services,
            "page_title": incident.title,
        },
    )


@router.post("/incidents/{incident_id}")
async def update_incident(
    incident_id: int,
    title: Annotated[str, Form()],
    status: Annotated[str, Form()],
    severity: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    is_resolved: Annotated[str | None, Form()] = None,
    end_datetime: Annotated[str | None, Form()] = None,
    scheduled_start: Annotated[str | None, Form()] = None,
    scheduled_end: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    old = await get_incident_by_id(db, incident_id)
    old_status = old.status if old else None
    old_resolved = old.is_resolved if old else False
    new_resolved = is_resolved == "on"

    parsed_end = _parse_form_dt(end_datetime)
    # Auto-set end_datetime to now when marking resolved and no end time was given
    if new_resolved and not parsed_end and not (old and old.end_datetime):
        parsed_end = datetime.utcnow()

    updates: dict = {
        "title": title,
        "status": status,
        "severity": severity or "",
        "description": description or None,
        "is_resolved": new_resolved,
        "end_datetime": parsed_end,
    }
    if scheduled_start is not None or scheduled_end is not None:
        updates["scheduled_start"] = _parse_form_dt(scheduled_start)
        updates["scheduled_end"] = _parse_form_dt(scheduled_end)
    await admin_update_incident(db, incident_id, **updates)

    # Record state-change timeline entry when status or resolved state changes
    effective_new = "resolved" if new_resolved else status
    effective_old = "resolved" if old_resolved else old_status
    if effective_new != effective_old:
        await add_state_change_entry(db, incident_id, effective_new)

    await db.commit()
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/incidents/{incident_id}/posts")
async def add_post(
    incident_id: int,
    content: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    await add_incident_post(db, incident_id, content)
    await db.commit()
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/services/refresh")
async def refresh_services(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Fetch all services from Graph API and register any new ones as disabled."""
    try:
        overviews = await fetch_health_overviews()
        for svc in overviews:
            name = svc.get("service", "")
            if name:
                await ensure_service_known(db, name)
        await db.commit()
    except Exception:
        logger.exception("Service discovery failed")
    return RedirectResponse(url="/admin/settings", status_code=303)


@router.post("/services/{service_name}/toggle")
async def toggle_service(
    service_name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Enable or disable a service on the status page. Triggers backfill when enabling."""
    result = await db.execute(
        sa_select(MonitoredService).where(MonitoredService.service_name == service_name)
    )
    svc = result.scalar_one_or_none()
    currently_enabled = svc.is_enabled if svc else False
    new_state = not currently_enabled
    await set_service_enabled(db, service_name, new_state)
    await db.commit()

    if new_state:
        asyncio.create_task(_backfill_service(service_name))
        _schedule_delayed_poll(delay=8.0)  # debounced: cancels any pending poll first

    return RedirectResponse(url="/admin/settings", status_code=303)


@router.post("/services/{service_name}/status")
async def set_service_status(
    service_name: str,
    status: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    await set_service_status_manual(db, service_name, status)
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/incidents/{incident_id}/suppress")
async def suppress_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    await toggle_suppress_incident(db, incident_id, suppress=True)
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/incidents/{incident_id}/unsuppress")
async def unsuppress_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    await toggle_suppress_incident(db, incident_id, suppress=False)
    await db.commit()
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.get("/maintenance/new")
async def new_maintenance_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    enabled_services = await get_enabled_services(db)
    return templates.TemplateResponse(
        request,
        "admin/maintenance_form.html",
        {
            "user": user,
            "services": enabled_services,
            "page_title": "Neue Wartung",
        },
    )


@router.post("/maintenance")
async def create_maintenance(
    title: Annotated[str, Form()],
    service_name: Annotated[str, Form()],
    description: Annotated[str | None, Form()] = None,
    scheduled_start: Annotated[str | None, Form()] = None,
    scheduled_end: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    incident = await create_manual_incident(
        db,
        title=title,
        service_name=service_name,
        classification="maintenance",
        status="scheduled",
        description=description or None,
        scheduled_start=_parse_form_dt(scheduled_start),
        scheduled_end=_parse_form_dt(scheduled_end),
    )
    await db.commit()
    return RedirectResponse(url=f"/admin/incidents/{incident.id}", status_code=303)


# ── Debug / Diagnostics ───────────────────────────────────────────────────────

@router.get("/debug")
async def debug_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    enabled = await get_enabled_services(db)
    return templates.TemplateResponse(
        request,
        "admin/debug.html",
        {
            "user": user,
            "enabled_services": set(enabled),
            "active_issues": None,
            "resolved_issues": None,
            "overviews": None,
            "errors": [],
            "page_title": "Debug – Graph API",
        },
    )


@router.post("/debug/fetch")
async def debug_fetch(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Live-fetch all Microsoft service health data and display raw results."""
    enabled = await get_enabled_services(db)
    errors: list[str] = []
    overviews: list[dict] = []
    active_issues: list[dict] = []
    resolved_issues: list[dict] = []

    try:
        overviews = await fetch_health_overviews()
    except Exception as exc:
        errors.append(f"Health Overviews: {exc}")

    try:
        active_issues = await fetch_active_issues()
    except Exception as exc:
        errors.append(f"Aktive Störungen: {exc}")

    try:
        resolved_issues = await fetch_recently_resolved_issues(days=30)
    except Exception as exc:
        errors.append(f"Kürzlich behoben: {exc}")

    return templates.TemplateResponse(
        request,
        "admin/debug.html",
        {
            "user": user,
            "enabled_services": set(enabled),
            "overviews": overviews,
            "active_issues": active_issues,
            "resolved_issues": resolved_issues,
            "errors": errors,
            "page_title": "Debug – Graph API",
        },
    )
