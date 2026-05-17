from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.auth import get_current_user
from app.config import settings
from app.database import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def admin_nav_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Counters and flash messages for the admin sidebar."""
    from app.flash import consume_flashes
    from app.models import Incident

    incidents_q = select(func.count(Incident.id)).where(
        Incident.is_resolved.is_(False),
        Incident.classification == "incident",
        Incident.is_suppressed.is_(False),
    )
    maintenances_q = select(func.count(Incident.id)).where(
        Incident.classification == "maintenance",
        Incident.is_resolved.is_(False),
    )
    incidents_count = (await db.execute(incidents_q)).scalar_one()
    maintenances_count = (await db.execute(maintenances_q)).scalar_one()
    return {
        "nav_active_incidents": incidents_count,
        "nav_scheduled_maintenances": maintenances_count,
        "flashes": consume_flashes(request),
    }


async def require_embed_access(
    request: Request,
    token: str | None = Query(default=None),
) -> None:
    """
    Grants access to /embed when either:
    - A non-empty EMBED_API_KEY is configured and ?token=<key> matches, OR
    - No API key is configured and the user has a valid OIDC session.
    """
    if settings.DISABLE_AUTH:
        return
    if settings.EMBED_API_KEY and token == settings.EMBED_API_KEY:
        return
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentifizierung erforderlich")
