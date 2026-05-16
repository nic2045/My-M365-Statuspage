from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import settings
from app.crud import build_status_page_data
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
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "user": user,
            "data": data,
            "page_title": settings.APP_TITLE,
        },
    )
