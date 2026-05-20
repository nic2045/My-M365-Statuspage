from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.auth import oauth
from app.config import settings

router = APIRouter(tags=["auth"])

# Only the claims the app actually needs are persisted in the (signed but
# unencrypted, client-readable) session cookie – avoids leaking the full
# OIDC userinfo payload.
_KEPT_CLAIMS = ("name", "email", "preferred_username", "sub", "oid", "roles")


def _safe_next(target: str | None) -> str:
    """Reject off-site redirect targets (open-redirect guard).

    Only same-origin absolute paths are allowed: must start with a single
    '/' and not with '//' or '/\\' (protocol-relative URLs).
    """
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return "/"
    return target


@router.get("/auth/login")
async def login(request: Request, next: str = "/"):
    request.session["next"] = _safe_next(next)
    return await oauth.microsoft.authorize_redirect(request, settings.AZURE_REDIRECT_URI)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.microsoft.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await oauth.microsoft.userinfo(token=token)
    request.session["user"] = {k: userinfo[k] for k in _KEPT_CLAIMS if k in userinfo}
    next_url = _safe_next(request.session.pop("next", "/"))
    return RedirectResponse(url=next_url, status_code=302)


@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    base_uri = settings.AZURE_REDIRECT_URI.replace("/auth/callback", "/")
    logout_url = (
        f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}"
        f"/oauth2/v2.0/logout?post_logout_redirect_uri={base_uri}"
    )
    return RedirectResponse(url=logout_url, status_code=302)
