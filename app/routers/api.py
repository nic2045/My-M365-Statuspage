from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import settings
from app.crud import build_status_page_data
from app.dependencies import get_db
from app.schemas import StatusPageSchema

router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/health")
async def health_check():
    """Docker healthcheck endpoint – no authentication required."""
    return {"status": "ok"}


@router.get("/status", response_model=StatusPageSchema)
async def api_status(
    _user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    return await build_status_page_data(db, settings.monitored_services_list)
