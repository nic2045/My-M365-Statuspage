from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import settings
from app.crud import (
    add_incident_post,
    add_state_change_entry,
    admin_update_incident,
    create_manual_incident,
    get_all_incidents,
    get_incident_by_id,
    get_resolved_incidents,
    get_scheduled_maintenances,
    set_service_status_manual,
)
from app.dependencies import get_db
from app.templates import templates

router = APIRouter(prefix="/admin", tags=["admin"])


def _parse_form_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


@router.get("/")
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    incidents = await get_all_incidents(db, include_resolved=False)
    resolved = await get_resolved_incidents(db, limit=10)
    maintenances = await get_scheduled_maintenances(db)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": user,
            "incidents": incidents,
            "resolved_incidents": resolved,
            "maintenances": maintenances,
            "services": settings.monitored_services_list,
            "page_title": f"Admin – {settings.APP_TITLE}",
        },
    )


@router.get("/incidents/new")
async def new_incident_form(
    request: Request,
    user: dict = Depends(require_auth),
):
    return templates.TemplateResponse(
        request,
        "admin/incident_form.html",
        {
            "user": user,
            "services": settings.monitored_services_list,
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
    return templates.TemplateResponse(
        request,
        "admin/incident_detail.html",
        {
            "user": user,
            "incident": incident,
            "services": settings.monitored_services_list,
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
    scheduled_start: Annotated[str | None, Form()] = None,
    scheduled_end: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_auth),
):
    old = await get_incident_by_id(db, incident_id)
    old_status = old.status if old else None
    old_resolved = old.is_resolved if old else False
    new_resolved = is_resolved == "on"

    updates: dict = {
        "title": title,
        "status": status,
        "severity": severity or "",
        "description": description or None,
        "is_resolved": new_resolved,
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


@router.get("/maintenance/new")
async def new_maintenance_form(
    request: Request,
    user: dict = Depends(require_auth),
):
    return templates.TemplateResponse(
        request,
        "admin/maintenance_form.html",
        {
            "user": user,
            "services": settings.monitored_services_list,
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
