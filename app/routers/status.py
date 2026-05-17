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

RANGE_TO_DAYS: dict[str, int] = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
DEFAULT_RANGE = "90d"


@router.get("/", response_class=HTMLResponse)
async def status_page(
    request: Request,
    range: str | None = None,
    user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    selected_range = range if range in RANGE_TO_DAYS else DEFAULT_RANGE
    days = RANGE_TO_DAYS[selected_range]

    enabled = await get_enabled_services(db)
    # Fall back to env var list if DB hasn't been seeded yet
    service_names = enabled or settings.monitored_services_list
    data = await build_status_page_data(db, service_names, days=days)
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
            "selected_range": selected_range,
            "range_options": list(RANGE_TO_DAYS.keys()),
            "range_days": days,
        },
    )
