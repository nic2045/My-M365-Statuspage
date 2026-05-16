from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.auth import oauth
from app.config import settings

router = APIRouter(tags=["auth"])


@router.get("/auth/login")
async def login(request: Request, next: str = "/"):
    request.session["next"] = next
    return await oauth.microsoft.authorize_redirect(request, settings.AZURE_REDIRECT_URI)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.microsoft.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await oauth.microsoft.userinfo(token=token)
    request.session["user"] = dict(userinfo)
    next_url = request.session.pop("next", "/")
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
