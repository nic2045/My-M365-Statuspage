from collections.abc import AsyncGenerator

from fastapi import HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.auth import get_current_user
from app.config import settings
from app.database import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def require_embed_access(
    request: Request,
    token: str | None = Query(default=None),
) -> None:
    """
    Grants access to /embed when either:
    - A non-empty EMBED_API_KEY is configured and ?token=<key> matches, OR
    - No API key is configured and the user has a valid OIDC session.
    """
    if settings.EMBED_API_KEY and token == settings.EMBED_API_KEY:
        return
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentifizierung erforderlich")
