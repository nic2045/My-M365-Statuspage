import asyncio
import csv
import logging
from datetime import date, datetime
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import desc
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import (
    get_app_default_language,
    get_azure_settings,
    get_effective_language,
    get_email_settings,
    save_app_default_language,
    save_azure_settings,
    save_email_settings,
    verify_azure_connection,
    verify_smtp_connection,
)
from app.auth import require_admin
from app.azure_secret_manager import AzureSecretSyncError, get_or_rotate_client_secret
from app.config import settings
from app.crud import (
    add_incident_post,
    add_state_change_entry,
    admin_update_incident,
    create_manual_incident,
    delete_source_label,
    delete_subscriber,
    ensure_service_known,
    get_all_incident_states,
    get_all_incidents,
    get_all_maintenances,
    get_all_monitored_services,
    get_all_severity_levels,
    get_all_source_labels,
    get_all_subscribers,
    get_certificate_dashboard_data,
    get_distinct_sources,
    get_enabled_services,
    get_enabled_services_with_status,
    get_http_dashboard_data,
    get_incident_by_id,
    get_known_groups,
    get_sla_breach_reasons,
    get_sla_for_month,
    move_service,
    publish_incident_update,
    search_global,
    set_service_enabled,
    set_service_group,
    set_service_status_manual,
    set_show_uptime_percentage,
    toggle_suppress_incident,
    upsert_source_label,
)
from app.crud import delete_incident as crud_delete_incident
from app.database import AsyncSessionLocal
from app.dependencies import admin_nav_context, get_db
from app.event_bus import StatusEvent, get_event_bus
from app.flash import flash
from app.graph_client import (
    fetch_active_issues,
    fetch_health_overviews,
    fetch_issues_since,
    fetch_recently_resolved_issues,
)
from app.i18n import LABELS, LABELS_BY_LANG
from app.models import MonitoredService
from app.notifications import dispatch_incident_notifications, send_test_email
from app.templates import templates
from app.translate_client import translate_text
from app.url_utils import normalize_url

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
    # boundaries is guaranteed non-empty (always has at least start_datetime)
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
    async with AsyncSessionLocal() as db:
        try:
            issues = await fetch_issues_since(service_name, days=90)
            synced = 0
            for issue in issues:
                await sync_issue_as_incident(db, issue)
                synced += 1
            await db.commit()
            logger.info("Historical incident sync completed for %s (%d of %d issues)", service_name, synced, len(issues))
        except Exception:
            await db.rollback()
            logger.exception("Historical incident sync failed for %s", service_name)


# Tracks a pending delayed poll so it can be cancelled and restarted when
# another service is enabled before the timer fires (debounce behaviour).
_pending_poll_task: asyncio.Task | None = None
_poll_task_lock = asyncio.Lock()


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


async def _schedule_delayed_poll(delay: float = 8.0) -> None:
    """Cancel any pending delayed poll and start a fresh one."""
    global _pending_poll_task
    async with _poll_task_lock:
        if _pending_poll_task and not _pending_poll_task.done():
            _pending_poll_task.cancel()
        _pending_poll_task = asyncio.create_task(_delayed_poll(delay))


@router.get("/")
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    services_with_status = await get_enabled_services_with_status(db)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": user,
            "services": services_with_status,
            "page_title": f"Admin – {settings.APP_TITLE}",
            **nav,
        },
    )


@router.get("/search")
async def admin_search(
    q: str = "",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """JSON endpoint backing the Cmd+K palette in the admin area."""
    return JSONResponse(await search_global(db, q))


@router.get("/settings")
async def admin_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    (
        all_services,
        known_groups,
        subscribers,
        email_cfg,
        azure_cfg,
        source_labels,
        severity_levels,
        incident_states,
        app_lang,
    ) = await asyncio.gather(
        get_all_monitored_services(db),
        get_known_groups(db),
        get_all_subscribers(db),
        get_email_settings(db),
        get_azure_settings(db),
        get_all_source_labels(db),
        get_all_severity_levels(db),
        get_all_incident_states(db),
        get_app_default_language(db),
    )
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
            "source_labels": source_labels,
            "severity_levels": severity_levels,
            "incident_states": incident_states,
            "app_default_language": app_lang or settings.DEFAULT_LANGUAGE,
            "page_title": f"{LABELS['settings.title']} – {settings.APP_TITLE}",
            **nav,
        },
    )


@router.post("/settings/language")
async def admin_save_language(
    request: Request,
    default_language: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    if default_language not in LABELS_BY_LANG:
        raise HTTPException(status_code=400, detail="unsupported language")
    await save_app_default_language(db, default_language)
    await db.commit()
    flash(request, LABELS["toast.language_saved"])
    return RedirectResponse(url="/admin/settings#language", status_code=303)


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
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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


@router.post("/settings/azure/openbao")
async def admin_sync_azure_secret_from_openbao(
    request: Request,
    force: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Get-or-rotate AZURE_CLIENT_SECRET via OpenBao (see app/azure_secret_manager.py).

    Uses the currently saved tenant/client ID (form save via /settings/azure is
    still how those are set) - this only ever touches the secret itself.
    """
    azure_cfg = await get_azure_settings(db)
    try:
        result = await get_or_rotate_client_secret(
            db, tenant_id=azure_cfg.tenant_id, client_id=azure_cfg.client_id, force=force == "1"
        )
    except AzureSecretSyncError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(url="/admin/settings#azure", status_code=303)
    await db.commit()

    if result.rotated:
        flash(
            request,
            f"Neues Client-Secret via Microsoft Graph erstellt und in OpenBao abgelegt "
            f"(gültig bis {result.expires_on}).",
            "success",
        )
    else:
        flash(
            request,
            f"Client-Secret aus OpenBao übernommen (gültig bis {result.expires_on}).",
            "success",
        )
    ok, msg = await verify_azure_connection(
        azure_cfg.tenant_id, azure_cfg.client_id, result.client_secret
    )
    flash(request, msg, "success" if ok else "error")
    return RedirectResponse(url="/admin/settings#azure", status_code=303)


@router.post("/api/source-labels")
async def api_save_source_label(
    request: Request,
    source: Annotated[str, Form()],
    label: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    src = source.strip()
    lbl = label.strip()
    if src and lbl:
        await upsert_source_label(db, src, lbl)
    from fastapi.responses import JSONResponse
    return JSONResponse({"ok": True})


@router.post("/settings/source-labels")
async def settings_save_source_label(
    request: Request,
    source: Annotated[str, Form()],
    label: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    src = source.strip()
    lbl = label.strip()
    if src and lbl:
        await upsert_source_label(db, src, lbl)
    flash(request, "Label gespeichert.")
    return RedirectResponse(url="/admin/settings#source-labels", status_code=303)


@router.post("/settings/source-labels/{source}/delete")
async def settings_delete_source_label(
    request: Request,
    source: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    await delete_source_label(db, source)
    flash(request, "Label entfernt.")
    return RedirectResponse(url="/admin/settings#source-labels", status_code=303)


@router.post("/subscribers/{subscriber_id}/delete")
async def admin_delete_subscriber(
    request: Request,
    subscriber_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    await delete_subscriber(db, subscriber_id)
    await db.commit()
    flash(request, LABELS["toast.subscriber_deleted"])
    return RedirectResponse(url="/admin/settings#subscribers", status_code=303)


@router.post("/settings/severities")
async def admin_create_severity(
    request: Request,
    name: Annotated[str, Form()],
    label: Annotated[str, Form()],
    color: Annotated[str, Form()] = "#000000",
    weight: Annotated[int, Form()] = 1,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    from app.models import SeverityLevel

    name_lower = name.lower().strip()
    if not name_lower:
        flash(request, "Name erforderlich.")
        return RedirectResponse(url="/admin/settings#severities", status_code=303)

    existing = (
        await db.execute(sa_select(SeverityLevel).where(SeverityLevel.name == name_lower))
    ).scalar_one_or_none()
    if existing:
        flash(request, f"Schweregrad '{name_lower}' existiert bereits.")
        return RedirectResponse(url="/admin/settings#severities", status_code=303)

    db.add(SeverityLevel(name=name_lower, label=label, color=color, weight=weight, display_order=weight))
    await db.commit()
    flash(request, f"Schweregrad '{label}' erstellt.")
    return RedirectResponse(url="/admin/settings#severities", status_code=303)


@router.post("/settings/states")
async def admin_create_state(
    request: Request,
    name: Annotated[str, Form()],
    label: Annotated[str, Form()],
    color: Annotated[str, Form()] = "#000000",
    is_terminal: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    from app.models import IncidentState

    name_lower = name.lower().strip()
    if not name_lower:
        flash(request, "Name erforderlich.")
        return RedirectResponse(url="/admin/settings#states", status_code=303)

    existing = (
        await db.execute(sa_select(IncidentState).where(IncidentState.name == name_lower))
    ).scalar_one_or_none()
    if existing:
        flash(request, f"State '{name_lower}' existiert bereits.")
        return RedirectResponse(url="/admin/settings#states", status_code=303)

    db.add(
        IncidentState(
            name=name_lower,
            label=label,
            color=color,
            is_terminal=is_terminal == "on",
            display_order=0,
        )
    )
    await db.commit()
    flash(request, f"State '{label}' erstellt.")
    return RedirectResponse(url="/admin/settings#states", status_code=303)


@router.post("/settings/severities/{name}")
async def admin_update_severity(
    request: Request,
    name: str,
    label: Annotated[str, Form()],
    color: Annotated[str, Form()] = "#000000",
    weight: Annotated[int, Form()] = 1,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    from app.models import SeverityLevel

    name_lower = name.lower().strip()
    severity = (
        await db.execute(sa_select(SeverityLevel).where(SeverityLevel.name == name_lower))
    ).scalar_one_or_none()
    if not severity or severity.is_system:
        flash(request, "Schweregrad kann nicht aktualisiert werden.")
        return RedirectResponse(url="/admin/settings#severities", status_code=303)

    severity.label = label
    severity.color = color
    severity.weight = weight
    await db.commit()
    flash(request, f"Schweregrad '{label}' aktualisiert.")
    return RedirectResponse(url="/admin/settings#severities", status_code=303)


@router.post("/settings/severities/{name}/delete")
async def admin_delete_severity(
    request: Request,
    name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    from app.models import SeverityLevel

    name_lower = name.lower().strip()
    severity = (
        await db.execute(sa_select(SeverityLevel).where(SeverityLevel.name == name_lower))
    ).scalar_one_or_none()
    if not severity or severity.is_system:
        flash(request, "System-Schweregrade können nicht gelöscht werden.")
        return RedirectResponse(url="/admin/settings#severities", status_code=303)

    await db.delete(severity)
    await db.commit()
    flash(request, "Schweregrad gelöscht.")
    return RedirectResponse(url="/admin/settings#severities", status_code=303)


@router.post("/settings/states/{name}")
async def admin_update_state(
    request: Request,
    name: str,
    label: Annotated[str, Form()],
    color: Annotated[str, Form()] = "#000000",
    is_terminal: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    from app.models import IncidentState

    name_lower = name.lower().strip()
    state = (
        await db.execute(sa_select(IncidentState).where(IncidentState.name == name_lower))
    ).scalar_one_or_none()
    if not state or state.is_system:
        flash(request, "Phase kann nicht aktualisiert werden.")
        return RedirectResponse(url="/admin/settings#states", status_code=303)

    state.label = label
    state.color = color
    state.is_terminal = is_terminal == "on"
    await db.commit()
    flash(request, f"Phase '{label}' aktualisiert.")
    return RedirectResponse(url="/admin/settings#states", status_code=303)


@router.post("/settings/states/{name}/delete")
async def admin_delete_state(
    request: Request,
    name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    from app.models import IncidentState

    name_lower = name.lower().strip()
    state = (
        await db.execute(sa_select(IncidentState).where(IncidentState.name == name_lower))
    ).scalar_one_or_none()
    if not state or state.is_system:
        flash(request, "System-Phasen können nicht gelöscht werden.")
        return RedirectResponse(url="/admin/settings#states", status_code=303)

    await db.delete(state)
    await db.commit()
    flash(request, "Phase gelöscht.")
    return RedirectResponse(url="/admin/settings#states", status_code=303)


@router.get("/incidents")
async def admin_incidents_all(
    request: Request,
    source: str | None = None,
    classification: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    """List ALL incidents (active + resolved). Supports ?source=manual|graph
    and ?classification=incident|advisory filters."""
    src_filter = source if source in ("manual", "graph") else None
    cls_filter = classification if classification in ("incident", "advisory") else None
    # When classification=advisory, only fetch advisories; otherwise fetch both
    if cls_filter == "advisory":
        incidents = []
        advisories_all = await get_all_incidents(
            db, include_resolved=True, classification="advisory", source=src_filter
        )
    elif cls_filter == "incident":
        incidents = await get_all_incidents(
            db, include_resolved=True, classification="incident", source=src_filter
        )
        advisories_all = []
    else:
        incidents = await get_all_incidents(
            db, include_resolved=True, classification="incident", source=src_filter
        )
        advisories_all = await get_all_incidents(
            db, include_resolved=True, classification="advisory", source=src_filter
        )
    advisories = [a for a in advisories_all if not a.is_suppressed]
    suppressed = [i for i in incidents if i.is_suppressed] + [
        a for a in advisories_all if a.is_suppressed
    ]
    incidents = [i for i in incidents if not i.is_suppressed]
    return templates.TemplateResponse(
        request,
        "admin/incidents_all.html",
        {
            "user": user,
            "incidents": incidents,
            "advisories": advisories,
            "suppressed": suppressed,
            "source_filter": src_filter,
            "classification_filter": cls_filter,
            "page_title": f"Alle Störungen – {settings.APP_TITLE}",
            **nav,
        },
    )


@router.get("/maintenances")
async def admin_maintenances_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    maintenances = await get_all_maintenances(db)
    return templates.TemplateResponse(
        request,
        "admin/maintenances_all.html",
        {
            "user": user,
            "maintenances": maintenances,
            "page_title": f"Wartungen – {settings.APP_TITLE}",
            **nav,
        },
    )


@router.get("/incidents/new")
async def new_incident_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    enabled_services, known_sources, all_labels = await asyncio.gather(
        get_enabled_services(db),
        get_distinct_sources(db),
        get_all_source_labels(db),
    )
    source_labels = {sl.source: sl.label for sl in all_labels}
    return templates.TemplateResponse(
        request,
        "admin/incident_form.html",
        {
            "user": user,
            "services": enabled_services,
            "known_sources": known_sources,
            "source_labels": source_labels,
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
    end_datetime: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "manual",
    external_id: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    incident = await create_manual_incident(
        db,
        title=title,
        service_name=service_name,
        classification=classification,
        severity=severity or "",
        description=description or None,
        start_datetime=_parse_form_dt(start_datetime),
        end_datetime=_parse_form_dt(end_datetime),
        source=source or "manual",
        external_id=external_id.strip() if external_id else None,
    )
    await db.commit()

    # Publish SSE event
    event_bus = get_event_bus()
    await event_bus.publish(
        StatusEvent(
            event_type="incident.created",
            service_name=service_name,
            incident_id=incident.id,
            title=title,
            status="active",
            timestamp=datetime.utcnow(),
        )
    )

    # Send notifications for new incidents (not advisories / maintenance)
    if classification == "incident":
        asyncio.create_task(
            dispatch_incident_notifications(
                service_name=service_name,
                incident_title=title,
                subject=LABELS["notify.new_incident"],
                description=description or "",
                incident_status="active",
            )
        )

    return RedirectResponse(url=f"/admin/incidents/{incident.id}", status_code=303)


@router.get("/incidents/{incident_id}")
async def incident_detail(
    request: Request,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    incident = await get_incident_by_id(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    enabled_services, known_sources, all_labels = await asyncio.gather(
        get_enabled_services(db),
        get_distinct_sources(db),
        get_all_source_labels(db),
    )
    source_labels = {sl.source: sl.label for sl in all_labels}
    return templates.TemplateResponse(
        request,
        "admin/incident_detail.html",
        {
            "user": user,
            "incident": incident,
            "services": enabled_services,
            "known_sources": known_sources,
            "source_labels": source_labels,
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
    start_datetime: Annotated[str | None, Form()] = None,
    end_datetime: Annotated[str | None, Form()] = None,
    scheduled_start: Annotated[str | None, Form()] = None,
    scheduled_end: Annotated[str | None, Form()] = None,
    source: Annotated[str | None, Form()] = None,
    external_id: Annotated[str | None, Form()] = None,
    postmortem_impact: Annotated[str | None, Form()] = None,
    postmortem_root_cause: Annotated[str | None, Form()] = None,
    postmortem_action_items: Annotated[str | None, Form()] = None,
    postmortem_timeline: Annotated[str | None, Form()] = None,
    postmortem_publish: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
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
        "postmortem_impact": postmortem_impact or None,
        "postmortem_root_cause": postmortem_root_cause or None,
        "postmortem_action_items": postmortem_action_items or None,
        "postmortem_timeline": postmortem_timeline or None,
    }
    if postmortem_publish == "on":
        updates["postmortem_published_at"] = datetime.utcnow()
    else:
        updates["postmortem_published_at"] = None
    if start_datetime:
        updates["start_datetime"] = _parse_form_dt(start_datetime)
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
        await add_state_change_entry(db, incident_id, effective_new, author=_user_email(user))

    await db.commit()

    # Publish SSE event for status change
    event_bus = get_event_bus()
    if old_resolved != new_resolved and new_resolved:
        event_type = "incident.resolved"
    elif old_status != status or old_resolved != new_resolved:
        event_type = "incident.updated"
    else:
        event_type = None

    if event_type and old:
        await event_bus.publish(
            StatusEvent(
                event_type=event_type,
                service_name=old.service_name,
                incident_id=incident_id,
                title=title,
                status=effective_new,
                timestamp=datetime.utcnow(),
            )
        )

    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/incidents/{incident_id}/delete")
async def delete_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
):
    do_notify = notify_subscribers == "on"
    await add_incident_post(
        db,
        incident_id,
        content,
        notify_subscribers=do_notify,
        author=_user_email(user),
    )
    incident = await get_incident_by_id(db, incident_id)
    await db.commit()

    if do_notify and incident:
        asyncio.create_task(
            dispatch_incident_notifications(
                service_name=incident.service_name,
                incident_title=incident.title,
                subject=LABELS["notify.update"],
                description=content,
                incident_status=incident.status,
            )
        )

    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/services/refresh")
async def refresh_services(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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
        await _schedule_delayed_poll(delay=8.0)  # debounced: cancels any pending poll first

    return RedirectResponse(url="/admin/settings", status_code=303)


@router.post("/services/{service_name}/uptime-toggle")
async def toggle_uptime_display(
    service_name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
):
    await set_service_status_manual(db, service_name, status)
    await db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/incidents/{incident_id}/suppress")
async def suppress_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    await toggle_suppress_incident(db, incident_id, suppress=True)
    await db.commit()
    return RedirectResponse(url="/admin/incidents", status_code=303)


@router.post("/incidents/{incident_id}/unsuppress")
async def unsuppress_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    await toggle_suppress_incident(db, incident_id, suppress=False)
    await db.commit()
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


def _user_email(user: dict) -> str | None:
    return user.get("email") or user.get("preferred_username")


@router.post("/incidents/{incident_id}/acknowledge")
async def acknowledge_incident(
    request: Request,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    email = _user_email(user)
    if email is None:
        raise HTTPException(status_code=400, detail="Kein Benutzer-Identifier verfügbar")
    now = datetime.utcnow()
    await admin_update_incident(
        db,
        incident_id,
        owner_email=email,
        acknowledged_at=now,
        acknowledged_by_email=email,
    )
    await db.commit()
    flash(request, LABELS["toast.acknowledged"])
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/incidents/{incident_id}/release")
async def release_incident(
    request: Request,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    await admin_update_incident(
        db,
        incident_id,
        owner_email=None,
        acknowledged_at=None,
        acknowledged_by_email=None,
    )
    await db.commit()
    flash(request, LABELS["toast.released"])
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/incidents/{incident_id}/updates/{update_id}/publish")
async def publish_update(
    request: Request,
    incident_id: int,
    update_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Operator approval for a Graph-synced message-center post - see
    crud.upsert_incident_updates for why these start unpublished."""
    ok = await publish_incident_update(db, incident_id, update_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Update not found")
    await db.commit()
    flash(request, LABELS["toast.update_published"])
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/incidents/{incident_id}/translate")
async def translate_incident(
    request: Request,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """One-time, admin-triggered DeepL translation of an incident's title,
    description and message-center posts. Not run automatically by the
    scheduler - DeepL's free tier has a monthly character cap, so translation
    is opt-in per incident rather than burning quota on every poll.
    """
    if not settings.DEEPL_API_KEY:
        flash(request, LABELS["toast.translate_not_configured"], level="error")
        return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)

    incident = await get_incident_by_id(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    lang = await get_effective_language(db)
    incident.title = await translate_text(incident.title, lang)
    if incident.description:
        incident.description = await translate_text(incident.description, lang)
    for update in incident.updates:
        update.content = await translate_text(update.content, lang, tag_handling="html")
    incident.translated_lang = lang

    await db.commit()
    flash(request, LABELS["toast.translated"])
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.get("/maintenance/new")
async def new_maintenance_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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
    user: dict = Depends(require_admin),
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


# ── SLA / Service Level Agreements ─────────────────────────────────────────

@router.get("/sla")
async def admin_sla(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    """Display SLA statistics (last 12 months per service)."""
    all_services = await get_all_monitored_services(db)

    today = date.today()
    sla_data = []

    for service in all_services:
        months_data = []
        for i in range(11, -1, -1):
            # Calculate year and month i months ago
            m = today.month - i
            y = today.year
            if m <= 0:
                y -= 1
                m += 12

            sla = await get_sla_for_month(db, service.service_name, y, m)
            months_data.append({
                "year": y,
                "month": m,
                "actual": sla["actual_percent"],
                "target": sla["target_percent"],
                "is_breach": sla["is_breach"],
            })

        # Calculate 12-month average
        avg = sum(m["actual"] for m in months_data) / len(months_data) if months_data else 0
        sla_data.append({
            "service_name": service.service_name,
            "target": service.sla_target_percentage,
            "months": months_data,
            "avg_12m": round(avg, 2),
            "months_met": sum(1 for m in months_data if not m["is_breach"]),
        })

    return templates.TemplateResponse(
        request,
        "admin/sla.html",
        {
            "user": user,
            "sla_data": sla_data,
            "page_title": "SLA-Statistik",
            **nav,
        },
    )


@router.get("/sla/export")
async def export_sla_csv(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Export 12-month SLA statistics as CSV."""
    all_services = await get_all_monitored_services(db)
    today = date.today()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Service", "Month", "Availability %", "Target %", "Met", "Downtime (minutes)"])

    for service in all_services:
        for i in range(11, -1, -1):
            m = today.month - i
            y = today.year
            if m <= 0:
                y -= 1
                m += 12

            sla = await get_sla_for_month(db, service.service_name, y, m)
            month_name = date(y, m, 1).strftime("%B %Y")
            met = "Yes" if not sla["is_breach"] else "No"
            writer.writerow([
                service.service_name,
                month_name,
                f"{sla['actual_percent']:.1f}",
                f"{sla['target_percent']:.1f}",
                met,
                f"{sla['downtime_minutes']:.1f}",
            ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sla_export.csv"},
    )


@router.get("/sla/{service_name}/{year}/{month}/reasons")
async def sla_breach_reasons(
    service_name: str,
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Get incidents that caused SLA breach for a service in a given month."""
    try:
        reasons = await get_sla_breach_reasons(db, service_name, year, month)
        return JSONResponse({
            "service_name": service_name,
            "year": year,
            "month": month,
            "reasons": reasons,
            "total_incidents": len(reasons),
        })
    except Exception:
        logger.exception(f"Failed to get SLA breach reasons for {service_name}")
        return JSONResponse({"error": "Failed to retrieve breach reasons"}, status_code=500)


@router.get("/checks")
async def list_checks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    """List all HTTP- and/or certificate-monitored services (either or both per service)."""
    result = await db.execute(
        sa_select(MonitoredService).where(
            MonitoredService.cert_hostname.is_not(None) | MonitoredService.http_url.is_not(None)
        )
    )
    checks = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "admin/checks.html",
        {
            "user": user,
            "checks": checks,
            "page_title": "Checks",
            **nav,
        },
    )


@router.post("/checks/create")
async def create_check(
    service_name: str = Form(...),
    enable_http: bool = Form(False),
    http_url: str | None = Form(None),
    http_expected_status: int = Form(200),
    check_interval_seconds: int | None = Form(None),
    enable_cert: bool = Form(False),
    cert_hostname: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Create a new check - HTTP, certificate, or both on the same service."""
    try:
        if not enable_http and not enable_cert:
            raise ValueError("At least one of HTTP or certificate must be selected")

        existing = await db.execute(
            sa_select(MonitoredService).where(MonitoredService.service_name == service_name)
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError(f"Service '{service_name}' already exists")

        normalized_http_url = None
        normalized_cert_hostname = None

        if enable_http and http_url:
            normalized_http_url, _ = normalize_url(http_url)

        if enable_cert and cert_hostname:
            _, normalized_cert_hostname = normalize_url(cert_hostname)

        svc = MonitoredService(
            service_name=service_name,
            service_type="check",
            http_url=normalized_http_url,
            http_expected_status=http_expected_status if enable_http else None,
            check_interval_seconds=check_interval_seconds if enable_http else None,
            cert_hostname=normalized_cert_hostname,
            is_enabled=True,
            group_name="Checks",
        )
        db.add(svc)
        await db.commit()
        logger.info(f"Created check: {service_name} (http={enable_http}, cert={enable_cert})")
    except Exception:
        await db.rollback()
        logger.exception("Failed to create check")

    return RedirectResponse(url="/admin/checks", status_code=303)


@router.post("/checks/{service_name}/delete")
async def delete_check(
    service_name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Delete a check (HTTP, certificate, or both)."""
    try:
        result = await db.execute(
            sa_select(MonitoredService).where(MonitoredService.service_name == service_name)
        )
        svc = result.scalar_one_or_none()
        if svc and (svc.cert_hostname or svc.http_url):
            await db.delete(svc)
            await db.commit()
            logger.info(f"Deleted check: {service_name}")
    except Exception:
        await db.rollback()
        logger.exception("Failed to delete check")

    return RedirectResponse(url="/admin/checks", status_code=303)


@router.post("/checks/{service_name}/update")
async def update_check(
    service_name: str,
    http_url: str | None = Form(None),
    http_expected_status: int | None = Form(None),
    check_interval_seconds: int | None = Form(None),
    cert_hostname: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Update an existing check (HTTP, certificate, or both)."""
    try:
        result = await db.execute(
            sa_select(MonitoredService).where(MonitoredService.service_name == service_name)
        )
        svc = result.scalar_one_or_none()
        if not svc:
            logger.warning(f"Check not found: {service_name}")
            return RedirectResponse(url="/admin/checks", status_code=303)

        if http_url:
            normalized_http_url, _ = normalize_url(http_url)
            svc.http_url = normalized_http_url
            svc.http_expected_status = http_expected_status or 200
            svc.check_interval_seconds = check_interval_seconds

        if cert_hostname:
            _, normalized_cert_hostname = normalize_url(cert_hostname)
            svc.cert_hostname = normalized_cert_hostname

        await db.commit()
        logger.info(f"Updated check: {service_name}")
    except Exception:
        await db.rollback()
        logger.exception("Failed to update check")

    return RedirectResponse(url="/admin/checks", status_code=303)


@router.get("/api/checks/{service_name}/latest-http")
async def get_latest_http_check(
    service_name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Get latest HTTP check result for a service."""
    from app.models import HttpCheckResult

    result = await db.execute(
        sa_select(HttpCheckResult)
        .where(HttpCheckResult.service_name == service_name)
        .order_by(desc(HttpCheckResult.checked_at))
        .limit(1)
    )
    check = result.scalar_one_or_none()

    if not check:
        return JSONResponse({"status": "no_data"}, status_code=200)

    return JSONResponse({
        "is_up": check.is_up,
        "status_code": check.status_code,
        "response_time_ms": check.response_time_ms,
        "error_message": check.error_message,
        "checked_at": check.checked_at.isoformat() if check.checked_at else None,
    })


@router.get("/api/checks/{service_name}/latest-certificate")
async def get_latest_certificate_check(
    service_name: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Get latest certificate check result for a service."""
    from app.models import CertificateCheckResult

    result = await db.execute(
        sa_select(CertificateCheckResult)
        .where(CertificateCheckResult.service_name == service_name)
        .order_by(desc(CertificateCheckResult.checked_at))
        .limit(1)
    )
    check = result.scalar_one_or_none()

    if not check:
        return JSONResponse({"status": "no_data"}, status_code=200)

    return JSONResponse({
        "status": check.status,
        "expires_at": check.expires_at.isoformat() if check.expires_at else None,
        "valid_from": check.valid_from.isoformat() if check.valid_from else None,
        "days_remaining": check.days_remaining,
        "common_name": check.common_name,
        "issuer": check.issuer,
        "serial_number": check.serial_number,
        "error_message": check.error_message,
        "checked_at": check.checked_at.isoformat() if check.checked_at else None,
    })


@router.get("/sensors")
async def sensors_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
    nav: dict = Depends(admin_nav_context),
):
    """Live dashboard for certificate and HTTP check sensors."""
    certificates = await get_certificate_dashboard_data(db)
    http_checks = await get_http_dashboard_data(db)

    return templates.TemplateResponse(
        request,
        "admin/sensors.html",
        {
            "user": user,
            "certificates": certificates,
            "http_checks": http_checks,
            "page_title": "Sensors",
            **nav,
        },
    )


@router.post("/api/sensors/poll-certificates")
async def manual_poll_certificates(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
) -> JSONResponse:
    """Manually trigger certificate poll (for testing)."""
    try:
        from app.scheduler import poll_certificates  # noqa: PLC0415
        await poll_certificates()
        return JSONResponse({"ok": True})
    except Exception:
        logger.exception("Manual certificate poll failed")
        return JSONResponse({"ok": False, "error": "Poll failed"}, status_code=500)


@router.post("/api/sensors/poll-http")
async def manual_poll_http(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
) -> JSONResponse:
    """Manually trigger HTTP checks poll (for testing)."""
    try:
        from app.scheduler import poll_http_checks  # noqa: PLC0415
        await poll_http_checks()
        return JSONResponse({"ok": True})
    except Exception:
        logger.exception("Manual HTTP checks poll failed")
        return JSONResponse({"ok": False, "error": "Poll failed"}, status_code=500)
