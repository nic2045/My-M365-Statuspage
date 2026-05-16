from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud import build_status_page_data
from app.dependencies import get_db, require_embed_access
from app.templates import templates

router = APIRouter(tags=["embed"])


@router.get("/embed", response_class=HTMLResponse)
async def embed_widget(
    request: Request,
    _: None = Depends(require_embed_access),
    db: AsyncSession = Depends(get_db),
):
    data = await build_status_page_data(db, settings.monitored_services_list)
    response = templates.TemplateResponse(
        "embed.html",
        {"request": request, "data": data},
    )
    # Allow embedding from any origin (required for Confluence DC / Typo3 iframes)
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    if "x-frame-options" in response.headers:
        del response.headers["x-frame-options"]
    return response
