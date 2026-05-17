import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import (
    get_azure_settings,
    get_email_settings,
    save_azure_settings,
    save_email_settings,
    verify_azure_connection,
    verify_smtp_connection,
)
from app.auth import require_auth
from app.config import settings
from app.crud import (
    add_incident_post,
    add_state_change_entry,
    admin_update_incident,
    create_manual_incident,
    delete_subscriber,
    ensure_service_known,
    get_all_incidents,
    get_all_monitored_services,
    get_all_subscribers,
    get_confirmed_subscribers,
    get_enabled_services,
    get_enabled_services_with_status,
    get_incident_by_id,
    get_known_groups,
    get_resolved_incidents,
    get_scheduled_maintenances,
    get_suppressed_incidents,
    move_service,
    set_service_enabled,
    set_service_group,
    set_service_status_manual,
    set_show_uptime_percentage,
    toggle_suppress_incident,
)
from app.crud import delete_incident as crud_delete_incident
from app.database import AsyncSessionLocal
from app.dependencies import admin_nav_context, get_db
from app.flash import flash
from app.graph_client import (
    fetch_active_issues,
    fetch_health_overviews,
    fetch_issues_since,
    fetch_recently_resolved_issues,
)
from app.i18n import LABELS
from app.models import MonitoredService
from app.notifications import send_incident_notification, send_teams_notification, send_test_email
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


def _compute_phase_segments(incident) -> list[dict]:
    """Build proportional phase segments for an incident's lifetime.

    Each segment is {"status": str, "weight": float} where weight is the
    duration of that phase in seconds (or 1 if start/end is unknown).
    The first phase is "active" from incident.start_datetime; each
    state-change update splits into a new phase; the last phase runs
    until end_datetime (or now if still open).
    """
    if incident.start_datetime is None:
        return []
    state_changes = sorted(
        [u for u in incident.updates if u.update_type == "state_change" and u.post_created_at],
        key=lambda u: u.post_created_at,
    )
    end = incident.end_datetime or datetime.utcnow()
    boundaries: list[tuple[datetime, str]] = [(incident.start_datetime, "active")]
    for sc in state_changes:
        boundaries.append((sc.post_created_at, sc.content))
    boundaries.append((end, boundaries[-1][1]))

    segments: list[dict] = []
    for i in range(len(boundaries) - 1):
        t0, status = boundaries[i]
        t1, _ = boundaries[i + 1]
        duration = max((t1 - t0).total_seconds(), 1.0)
        segments.append({"status": status, "weight": duration})
    return segments


async def _backfill_service(service_name: str) -> None:
    """Background task: fetch 90-day issue history and store as Incidents.

    The uptime bars on the status page derive their colors live from
    Incidents (see get_uptime_bars in crud.py), so pre-populating the
    Incidents table for the past 90 days seeds the bars immediately
    after a service is enabled – no synthetic ServiceStatus rows needed.
    """
    from app.scheduler import sync_issue_as_incident  # local import: avoids circular dep
    try:
        issues = await fetch_issues_since(service_name, days=90)
        synced = 0
        async with AsyncSessionLocal() as db:
            for issue in issues:
                await sync_issue_as_incident(db, issue)
                synced += 1
            await db.commit()
        logger.info("Historical incident sync completed for %s (%d of %d issues)", service_name, synced, len(issues))
    except Exception:
        logger.exception("Historical incident sync failed for %s", service_name)


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
    nav: dict = Depends(admin_nav_context),
):
    incidents = await get_all_incidents(
        db, include_resolved=False, classification="incident"
    )
    advisories = await get_all_incidents(
        db, include_resolved=False, classification="advisory"
    )
    resolved = await get_resolved_incidents(db, limit=10)
    suppressed = await get_suppressed_incidents(db)
    maintenances = await get_scheduled_maintenances(db)
    services_with_status = await get_enabled_services_with_status(db)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": user,
            "incidents": incidents,
            "advisories": advisories,
            "resolved_incidents": resolved,
            "suppressed_incidents": suppressed,
            "maintenances": maintenances,
            "services": services_with_status,
            "page_title": f"Admin – {settings.APP_TITLE}",
            **nav,
        },
    )


@router.get("/settings")
async def admin_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
    nav: dict = Depends(admin_nav_context),
):
    all_services = await get_all_monitored_services(db)
    known_groups = await get_known_groups(db)
    subscribers = await get_all_subscribers(db)
    email_cfg = await get_email_settings(db)
    azure_cfg = await get_azure_settings(db)
    return templates.TemplateResponse(
        request,
        "admin/settings.html",
        {
            "user": user,
            "all_services": all_services,
            "known_groups": known_groups,
            "subscribers": subscribers,
            "teams_webhook_urls": settings.TEAMS_WEBHOOK_URLS,
            "email_cfg": email_cfg,
            "azure_cfg": azure_cfg,
            "page_title": f"Einstellungen – {settings.APP_TITLE}",
            **nav,
        },
    )


@router.post("/settings/email")
async def admin_save_email_settings(
    request: Request,
    auth_method: Annotated[str, Form()],
    smtp_host: Annotated[str, Form()] = "",
    smtp_port: Annotated[int, Form()] = 587,
    smtp_user: Annotated[str, Form()] = "",
    smtp_pass: Annotated[str, Form()] = "",
    smtp_from: Annotated[str, Form()] = "",
    smtp_tls: Annotated[str | None, Form()] = None,
    graph_from_address: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    if auth_method not in {"none", "password", "graph_oauth2"}:
        auth_method = "none"
    effective_pass = smtp_pass if smtp_pass else None
    await save_email_settings(
        db,
        auth_method=auth_method,  # type: ignore[arg-type]
        smtp_host=smtp_host.strip(),
        smtp_port=smtp_port,
        smtp_user=smtp_user.strip(),
        # Treat empty submit as "keep existing password" (form shows placeholder)
        smtp_pass=effective_pass,
        smtp_from=smtp_from.strip(),
        smtp_tls=smtp_tls == "on",
        graph_from_address=graph_from_address.strip(),
    )
    await db.commit()
    flash(request, LABELS["toast.email_saved"])
    # Verify connection after save
    if auth_method == "password":
        # Reload to get the effective password (may have been preserved)
        from app.app_settings import get_email_settings as _get_cfg  # noqa: PLC0415
        cfg = await _get_cfg(db)
        ok, msg = await verify_smtp_connection(
            cfg.smtp_host, cfg.smtp_port, cfg.smtp_user, cfg.smtp_pass, cfg.smtp_tls
        )
        flash(request, msg, "success" if ok else "error")
    elif auth_method == "graph_oauth2":
        azure_cfg = await get_azure_settings(db)
        ok, msg = await verify_azure_connection(
            azure_cfg.tenant_id, azure_cfg.client_id, azure_cfg.client_secret
        )
        flash(request, msg, "success" if ok else "error")
    return RedirectResponse(url="/admin/settings#email", status_code=303)


@router.post("/settings/email/test")
async def admin_send_test_email(
    request: Request,
    to: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    ok, message = await send_test_email(to.strip())
    flash(request, message, "success" if ok else "error")
    return RedirectResponse(url="/admin/settings#email", status_code=303)


@router.post("/settings/azure")
async def admin_save_azure_settings(
    request: Request,
    tenant_id: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    client_secret: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    await save_azure_settings(
        db,
        tenant_id=tenant_id.strip(),
        client_id=client_id.strip(),
        client_secret=client_secret if client_secret else None,
    )
    await db.commit()
    flash(request, LABELS["toast.azure_saved"])
    # Verify connection with the saved credentials
    azure_cfg = await get_azure_settings(db)
    ok, msg = await verify_azure_connection(
        azure_cfg.tenant_id, azure_cfg.client_id, azure_cfg.client_secret
    )
    flash(request, msg, "success" if ok else "error")
    return RedirectResponse(url="/admin/settings#azure", status_code=303)


@router.post("/subscribers/{subscriber_id}/delete")
async def admin_delete_subscriber(
    request: Request,
    subscriber_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    await delete_subscriber(db, subscriber_id)
    await db.commit()
    flash(request, LABELS["toast.subscriber_deleted"])
    return RedirectResponse(url="/admin/settings#subscribers", status_code=303)


@router.get("/incidents")
async def admin_incidents_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
    nav: dict = Depends(admin_nav_context),
):
    """List ALL incidents (active + resolved). Suppressed shown for incidents
    (dimmed) but hidden from advisories per UX preference."""
    incidents = await get_all_incidents(
        db, include_resolved=True, classification="incident"
    )
    advisories_all = await get_all_incidents(
        db, include_resolved=True, classification="advisory"
    )
    advisories = [a for a in advisories_all if not a.is_suppressed]
    return templates.TemplateResponse(
        request,
        "admin/incidents_all.html",
        {
            "user": user,
            "incidents": incidents,
            "advisories": advisories,
            "page_title": f"Alle Störungen – {settings.APP_TITLE}",
            **nav,
        },
    )


@router.get("/incidents/new")
async def new_incident_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
    nav: dict = Depends(admin_nav_context),
):
    enabled_services = await get_enabled_services(db)
    return templates.TemplateResponse(
        request,
        "admin/incident_form.html",
        {
            "user": user,
            "services": enabled_services,
            "page_title": "Neue Störung / Hinweis",
            **nav,
        },
    )


@router.post("/incidents")
async def create_incident(
    title: Annotated[str, Form()],
    service_name: Annotated[str, Form()],
    classification: Annotated[str, Form()],
    severity: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    start_datetime: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "manual",
    external_id: Annotated[str | None, Form()] = None,
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
        start_datetime=_parse_form_dt(start_datetime),
        source=source or "manual",
        external_id=external_id.strip() if external_id else None,
    )
    await db.commit()

    # Send notifications for new incidents (not advisories / maintenance)
    if classification == "incident":
        confirmed = await get_confirmed_subscribers(db)
        if confirmed:
            unsub_urls = {
                s.email: f"{settings.BASE_URL}/unsubscribe/{s.unsubscribe_token}"
                for s in confirmed
            }
            asyncio.create_task(
                send_incident_notification(
                    subscribers=[s.email for s in confirmed],
                    subject=LABELS["notify.new_incident"],
                    incident_title=title,
                    service_name=service_name,
                    description=description or "",
                    status_url=settings.BASE_URL,
                    unsubscribe_urls=unsub_urls,
                )
            )
        asyncio.create_task(
            send_teams_notification(
                incident_title=title,
                service_name=service_name,
                status="interrupted",
                description=description or "",
                status_url=settings.BASE_URL,
            )
        )

    return RedirectResponse(url=f"/admin/incidents/{incident.id}", status_code=303)


@router.get("/incidents/{incident_id}")
async def incident_detail(
    request: Request,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
    nav: dict = Depends(admin_nav_context),
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
            "phase_segments": _compute_phase_segments(incident),
            "page_title": incident.title,
            **nav,
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
    source: Annotated[str | None, Form()] = None,
    external_id: Annotated[str | None, Form()] = None,
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
        "external_id": external_id.strip() if external_id else None,
    }
    if source:
        updates["source"] = source
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


@router.post("/incidents/{incident_id}/delete")
async def delete_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    deleted = await crud_delete_incident(db, incident_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/incidents/{incident_id}/posts")
async def add_post(
    incident_id: int,
    content: Annotated[str, Form()],
    notify_subscribers: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    do_notify = notify_subscribers == "on"
    await add_incident_post(
        db,
        incident_id,
        content,
        notify_subscribers=do_notify,
    )
    incident = await get_incident_by_id(db, incident_id)
    await db.commit()

    if do_notify and incident:
        confirmed = await get_confirmed_subscribers(db)
        if confirmed:
            unsub_urls = {
                s.email: f"{settings.BASE_URL}/unsubscribe/{s.unsubscribe_token}"
                for s in confirmed
            }
            asyncio.create_task(
                send_incident_notification(
                    subscribers=[s.email for s in confirmed],
                    subject=LABELS["notify.update"],
                    incident_title=incident.title,
                    service_name=incident.service_name,
                    description=content,
                    status_url=settings.BASE_URL,
                    unsubscribe_urls=unsub_urls,
                )
            )
        asyncio.create_task(
            send_teams_notification(
                incident_title=incident.title,
                service_name=incident.service_name,
                status=incident.status,
                description=content,
                status_url=settings.BASE_URL,
            )
        )

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


@router.post("/services/{service_name}/uptime-toggle")
async def toggle_uptime_display(
    service_name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Toggle whether the 90-day uptime percentage is shown for this service."""
    result = await db.execute(
        sa_select(MonitoredService).where(MonitoredService.service_name == service_name)
    )
    svc = result.scalar_one_or_none()
    new_state = not (svc.show_uptime_percentage if svc else True)
    await set_show_uptime_percentage(db, service_name, new_state)
    await db.commit()
    return RedirectResponse(url="/admin/settings", status_code=303)


@router.post("/services/{service_name}/move")
async def admin_move_service(
    request: Request,
    service_name: str,
    direction: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Move service one slot up or down within its group (changes public-page order)."""
    moved = await move_service(db, service_name, direction)
    await db.commit()
    if moved:
        flash(request, LABELS["toast.service_moved"])
    return RedirectResponse(url="/admin/settings", status_code=303)


@router.post("/services/{service_name}/group")
async def update_service_group(
    service_name: str,
    group_name: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    """Assign (or clear) the group for a monitored service."""
    await set_service_group(db, service_name, group_name)
    await db.commit()
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
    nav: dict = Depends(admin_nav_context),
):
    enabled_services = await get_enabled_services(db)
    return templates.TemplateResponse(
        request,
        "admin/maintenance_form.html",
        {
            "user": user,
            "services": enabled_services,
            "page_title": "Neue Wartung",
            **nav,
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
    nav: dict = Depends(admin_nav_context),
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
            **nav,
        },
    )


@router.post("/debug/fetch")
async def debug_fetch(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
    nav: dict = Depends(admin_nav_context),
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
            **nav,
        },
    )
