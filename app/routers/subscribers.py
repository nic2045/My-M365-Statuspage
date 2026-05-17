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
from app.notifications import send_confirmation_email
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["subscribers"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def get_db():
    async with AsyncSessionLocal() as db:
        yield db


@router.post("/subscribe")
async def subscribe(
    request: Request,
    email: Annotated[str, Form()],
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return templates.TemplateResponse(
            request, "subscribe_result.html",
            {"ok": False, "message": "Ungültige E-Mail-Adresse.", "page_title": "Anmeldung"}
        )

    sub = await create_subscriber(db, email)
    if sub is None:
        # Already subscribed – still show success to avoid enumeration
        return templates.TemplateResponse(
            request, "subscribe_result.html",
            {"ok": True, "page_title": "Anmeldung"}
        )

    await db.commit()
    confirm_url = f"{settings.BASE_URL}/subscribe/confirm/{sub.confirm_token}"
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
