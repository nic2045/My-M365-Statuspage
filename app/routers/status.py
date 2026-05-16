from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import settings
from app.crud import (
    build_status_page_data,
    get_enabled_services,
    get_resolved_incidents,
    get_scheduled_maintenances,
)
from app.dependencies import get_db
from app.templates import templates

router = APIRouter(tags=["status"])


@router.get("/", response_class=HTMLResponse)
async def status_page(
    request: Request,
    user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    enabled = await get_enabled_services(db)
    # Fall back to env var list if DB hasn't been seeded yet
    service_names = enabled or settings.monitored_services_list
    data = await build_status_page_data(db, service_names)
    maintenances = await get_scheduled_maintenances(db)
    recent_resolved = await get_resolved_incidents(db, limit=50, days=30)
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "user": user,
            "data": data,
            "maintenances": maintenances,
            "recent_resolved": recent_resolved,
            "page_title": settings.APP_TITLE,
        },
    )
