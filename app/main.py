import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequired
from app.config import settings
from app.database import AsyncSessionLocal, init_db
from app.i18n import (
    LABELS_BY_LANG,
    reset_current_language,
    resolve_language,
    set_current_language,
)
from app.routers import admin, api, auth_router, embed, status
from app.routers.subscribers import router as subscribers_router
from app.scheduler import start_scheduler, stop_scheduler

LANG_COOKIE = "lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.APP_TITLE,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE,
    https_only=not settings.DEBUG,
    same_site="lax",
)

@app.middleware("http")
async def language_middleware(request: Request, call_next):
    """Resolve the visitor's UI language once per request.

    Cookie wins. If no cookie, fall back to the Accept-Language header (the
    visitor's browser/OS preference), then to the admin-configured default,
    then to the server's locale, then to DEFAULT_LANGUAGE.
    """
    cookie = request.cookies.get(LANG_COOKIE)
    app_default: str | None = None
    if not cookie:
        try:
            from app.app_settings import (  # noqa: PLC0415
                get_app_default_language,
            )
            async with AsyncSessionLocal() as db:
                app_default = await get_app_default_language(db)
        except Exception:  # noqa: BLE001
            app_default = None
    lang = resolve_language(
        cookie=cookie,
        accept_language=request.headers.get("accept-language"),
        app_default=app_default or settings.DEFAULT_LANGUAGE,
    )
    token = set_current_language(lang)
    request.state.lang = lang
    try:
        response = await call_next(request)
    finally:
        reset_current_language(token)
    return response


@app.get("/lang/{code}", include_in_schema=False)
async def set_language(request: Request, code: str):
    """Persist the visitor's language choice and redirect back."""
    if code not in LABELS_BY_LANG:
        return RedirectResponse(url="/", status_code=303)
    next_url = request.query_params.get("next") or request.headers.get("referer") or "/"
    if not next_url.startswith("/"):
        # Don't allow off-site redirects via the ?next= param.
        next_url = "/"
    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie(
        LANG_COOKIE,
        code,
        max_age=LANG_COOKIE_MAX_AGE,
        httponly=False,
        samesite="lax",
        secure=not settings.DEBUG,
    )
    return response


app.mount("/static", StaticFiles(directory="static"), name="static")


# PWA: service worker must be served from origin root for its scope to cover
# the whole app. The headers ensure the browser always revalidates the SW
# itself (so updates roll out immediately on next page load).
@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(url=f"/auth/login?next={exc.next_path}", status_code=302)


app.include_router(auth_router.router)
app.include_router(status.router)
app.include_router(embed.router)
app.include_router(api.router)
app.include_router(admin.router)
app.include_router(subscribers_router)
