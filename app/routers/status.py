from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import settings
from app.crud import build_status_page_data, get_scheduled_maintenances
from app.dependencies import get_db
from app.templates import templates

router = APIRouter(tags=["status"])


@router.get("/", response_class=HTMLResponse)
async def status_page(
    request: Request,
    user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    data = await build_status_page_data(db, settings.monitored_services_list)
    maintenances = await get_scheduled_maintenances(db)
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "user": user,
            "data": data,
            "maintenances": maintenances,
            "page_title": settings.APP_TITLE,
        },
    )
