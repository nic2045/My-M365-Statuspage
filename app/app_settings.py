"""Runtime app settings stored in DB (overrides env when set).

Used for SMTP credentials and similar config that needs to be editable
without redeploying. Env values from app.config.settings serve as fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as env_settings
from app.models import AppSetting

AuthMethod = Literal["none", "password", "graph_oauth2"]


@dataclass
class EmailSettings:
    """Effective email-sending configuration (DB layered over env defaults)."""
    auth_method: AuthMethod
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    smtp_from: str
    smtp_tls: bool
    graph_from_address: str
    is_configured: bool


SMTP_KEYS = {
    "email.auth_method",
    "email.smtp_host",
    "email.smtp_port",
    "email.smtp_user",
    "email.smtp_pass",
    "email.smtp_from",
    "email.smtp_tls",
    "email.graph_from_address",
}


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AppSetting.key, AppSetting.value))
    return dict(result.fetchall())


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    """Upsert one setting row."""
    stmt = (
        sqlite_insert(AppSetting)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )
    await db.execute(stmt)


async def get_email_settings(db: AsyncSession) -> EmailSettings:
    """Load email config: DB row wins, falls back to env var."""
    rows = await get_all_settings(db)

    def _str(key: str, fallback: str) -> str:
        return rows.get(key, fallback)

    def _int(key: str, fallback: int) -> int:
        try:
            return int(rows.get(key, str(fallback)))
        except (ValueError, TypeError):
            return fallback

    def _bool(key: str, fallback: bool) -> bool:
        raw = rows.get(key)
        if raw is None:
            return fallback
        return raw.lower() in {"1", "true", "yes", "on"}

    raw_method = rows.get("email.auth_method", "")
    # Migrate legacy env-only config: if no method set but SMTP_HOST present,
    # assume password auth.
    if not raw_method:
        raw_method = "password" if env_settings.SMTP_HOST else "none"
    if raw_method not in {"none", "password", "graph_oauth2"}:
        raw_method = "none"

    smtp_host = _str("email.smtp_host", env_settings.SMTP_HOST)
    smtp_user = _str("email.smtp_user", env_settings.SMTP_USER)
    smtp_from = _str("email.smtp_from", env_settings.SMTP_FROM)
    graph_from = _str("email.graph_from_address", "")

    if raw_method == "password":
        configured = bool(smtp_host)
    elif raw_method == "graph_oauth2":
        configured = bool(graph_from and env_settings.AZURE_TENANT_ID
                          and env_settings.AZURE_CLIENT_ID
                          and env_settings.AZURE_CLIENT_SECRET)
    else:
        configured = False

    return EmailSettings(
        auth_method=raw_method,  # type: ignore[arg-type]
        smtp_host=smtp_host,
        smtp_port=_int("email.smtp_port", env_settings.SMTP_PORT),
        smtp_user=smtp_user,
        smtp_pass=_str("email.smtp_pass", env_settings.SMTP_PASS),
        smtp_from=smtp_from or smtp_user,
        smtp_tls=_bool("email.smtp_tls", env_settings.SMTP_TLS),
        graph_from_address=graph_from,
        is_configured=configured,
    )


async def save_email_settings(
    db: AsyncSession,
    *,
    auth_method: AuthMethod,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str | None,
    smtp_from: str,
    smtp_tls: bool,
    graph_from_address: str,
) -> None:
    """Save form values to DB. Pass smtp_pass=None to leave existing value."""
    await set_setting(db, "email.auth_method", auth_method)
    await set_setting(db, "email.smtp_host", smtp_host)
    await set_setting(db, "email.smtp_port", str(smtp_port))
    await set_setting(db, "email.smtp_user", smtp_user)
    if smtp_pass is not None:
        await set_setting(db, "email.smtp_pass", smtp_pass)
    await set_setting(db, "email.smtp_from", smtp_from)
    await set_setting(db, "email.smtp_tls", "true" if smtp_tls else "false")
    await set_setting(db, "email.graph_from_address", graph_from_address)
