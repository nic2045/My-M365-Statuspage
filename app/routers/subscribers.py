"""Public subscription routes: subscribe, confirm, unsubscribe."""
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud import (
    confirm_subscriber,
    create_subscriber,
    delete_subscriber,
    get_subscriber_by_unsub_token,
)
from app.database import AsyncSessionLocal
from app.notifications import send_confirmation_email, send_teams_confirmation
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscribers"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HTTPS_URL_RE = re.compile(r"^https://\S+$")


async def get_db():
    async with AsyncSessionLocal() as db:
        yield db


@router.post("/subscribe")
async def subscribe(
    request: Request,
    email: Annotated[str, Form()],
    channel: Annotated[str, Form()] = "email",
    teams_webhook_url: Annotated[str | None, Form()] = None,
    services: Annotated[list[str] | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return templates.TemplateResponse(
            request, "subscribe_result.html",
            {"ok": False, "message": "Ungültige E-Mail-Adresse.", "page_title": "Anmeldung"}
        )

    channel = channel if channel in ("email", "teams") else "email"
    webhook = (teams_webhook_url or "").strip() or None
    if channel == "teams" and not (webhook and _HTTPS_URL_RE.match(webhook)):
        return templates.TemplateResponse(
            request, "subscribe_result.html",
            {"ok": False, "message": "Ungültige Teams-Webhook-URL.", "page_title": "Anmeldung"}
        )

    sub = await create_subscriber(
        db, email,
        channel=channel,
        teams_webhook_url=webhook if channel == "teams" else None,
        services=services,
    )
    if sub is None:
        # Already subscribed – still show success to avoid enumeration
        return templates.TemplateResponse(
            request, "subscribe_result.html",
            {"ok": True, "page_title": "Anmeldung"}
        )

    await db.commit()
    confirm_url = f"{settings.BASE_URL}/subscribe/confirm/{sub.confirm_token}"
    if channel == "teams":
        await send_teams_confirmation(webhook, confirm_url)
    else:
        await send_confirmation_email(email, confirm_url)
    return templates.TemplateResponse(
        request, "subscribe_result.html",
        {"ok": True, "page_title": "Anmeldung"}
    )


@router.get("/subscribe/confirm/{token}")
async def confirm_subscription(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    sub = await confirm_subscriber(db, token)
    if sub is None:
        return templates.TemplateResponse(
            request, "subscribe_result.html",
            {
                "ok": False,
                "message": "Bestätigungslink ungültig oder bereits verwendet.",
                "page_title": "Bestätigung",
            }
        )
    await db.commit()
    return templates.TemplateResponse(
        request, "subscribe_result.html",
        {"ok": True, "confirmed": True, "page_title": "Bestätigung"}
    )


@router.get("/unsubscribe/{token}")
async def unsubscribe(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    sub = await get_subscriber_by_unsub_token(db, token)
    if sub:
        await delete_subscriber(db, sub.id)
        await db.commit()
    return templates.TemplateResponse(
        request, "subscribe_result.html",
        {"ok": True, "unsubscribed": True, "page_title": "Abmeldung"}
    )
