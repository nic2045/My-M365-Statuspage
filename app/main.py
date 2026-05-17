import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequired
from app.config import settings
from app.database import init_db
from app.routers import admin, api, auth_router, embed, status
from app.routers.subscribers import router as subscribers_router
from app.scheduler import start_scheduler, stop_scheduler

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
