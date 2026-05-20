import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings

logger = logging.getLogger(__name__)

oauth = OAuth()
oauth.register(
    name="microsoft",
    client_id=settings.AZURE_CLIENT_ID,
    client_secret=settings.AZURE_CLIENT_SECRET,
    server_metadata_url=settings.oidc_metadata_url,
    client_kwargs={
        "scope": "openid profile email",
        "response_type": "code",
    },
)


class LoginRequired(Exception):
    def __init__(self, next_path: str = "/"):
        self.next_path = next_path


async def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


_DEV_USER = {"name": "Dev User", "email": "dev@localhost", "sub": "dev"}


async def require_auth(request: Request) -> dict:
    if settings.DISABLE_AUTH:
        return _DEV_USER
    user = await get_current_user(request)
    if user is None:
        raise LoginRequired(next_path=str(request.url.path))
    return user


def _user_identifier(user: dict) -> str:
    return (user.get("email") or user.get("preferred_username") or "").strip().lower()


def _user_roles(user: dict) -> list[str]:
    """App roles from the token's `roles` claim, lower-cased."""
    roles = user.get("roles")
    return [str(r).strip().lower() for r in roles] if isinstance(roles, list) else []


async def require_admin(request: Request) -> dict:
    """Authenticated *and* authorized for the admin area.

    Authorization is granted when the user carries the configured Entra ID
    app role (ADMIN_ROLE) or is on the optional ADMIN_EMAILS allowlist.

    Legacy fallback: if no allowlist is configured *and* the token carries no
    `roles` claim at all (i.e. app roles have not been set up yet), every
    authenticated user is allowed so upgrades don't lock admins out. A warning
    is emitted at startup in that case.
    """
    user = await require_auth(request)
    if settings.DISABLE_AUTH:
        return user

    allowlist = settings.admin_emails_list
    required_role = settings.ADMIN_ROLE.strip().lower()
    roles = _user_roles(user)

    if required_role and required_role in roles:
        return user
    if allowlist and _user_identifier(user) in allowlist:
        return user
    # No authorization rules in effect anywhere → legacy allow-all.
    if not allowlist and not roles:
        return user

    logger.warning(
        "Admin access denied for %r (roles=%r, required_role=%r)",
        _user_identifier(user), roles, required_role,
    )
    raise HTTPException(status_code=403, detail="Kein Admin-Zugriff für dieses Konto.")
