"""Runtime app settings stored in DB (overrides env when set).

Used for SMTP credentials and similar config that needs to be editable
without redeploying. Env values from app.config.settings serve as fallback.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as env_settings
from app.models import AppSetting

logger = logging.getLogger(__name__)

AuthMethod = Literal["none", "password", "graph_oauth2"]

_PLACEHOLDER_VALUES = {"your-tenant-id", "your-client-id", "your-client-secret", ""}


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
        az_tenant = rows.get("azure.tenant_id") or env_settings.AZURE_TENANT_ID
        az_client = rows.get("azure.client_id") or env_settings.AZURE_CLIENT_ID
        az_secret = rows.get("azure.client_secret") or env_settings.AZURE_CLIENT_SECRET
        configured = bool(
            graph_from and az_tenant and az_client and az_secret
            and az_tenant not in _PLACEHOLDER_VALUES
            and az_client not in _PLACEHOLDER_VALUES
        )
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


# ── Azure AD settings ─────────────────────────────────────────────────────────


@dataclass
class AzureSettings:
    """Effective Azure AD credentials (DB layered over env defaults)."""
    tenant_id: str
    client_id: str
    client_secret: str
    is_configured: bool


async def get_azure_settings(db: AsyncSession) -> AzureSettings:
    """Load Azure AD config: DB row wins, falls back to env var."""
    rows = await get_all_settings(db)
    tenant_id = rows.get("azure.tenant_id") or env_settings.AZURE_TENANT_ID
    client_id = rows.get("azure.client_id") or env_settings.AZURE_CLIENT_ID
    client_secret = rows.get("azure.client_secret") or env_settings.AZURE_CLIENT_SECRET
    is_configured = bool(
        tenant_id and client_id and client_secret
        and tenant_id not in _PLACEHOLDER_VALUES
        and client_id not in _PLACEHOLDER_VALUES
        and client_secret not in _PLACEHOLDER_VALUES
    )
    return AzureSettings(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        is_configured=is_configured,
    )


async def save_azure_settings(
    db: AsyncSession,
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str | None,
) -> None:
    """Save Azure AD form values. Pass client_secret=None to keep existing."""
    await set_setting(db, "azure.tenant_id", tenant_id)
    await set_setting(db, "azure.client_id", client_id)
    if client_secret is not None:
        await set_setting(db, "azure.client_secret", client_secret)


# ── Azure connectivity check ──────────────────────────────────────────────────

def _map_msal_error(error: str, error_description: str) -> str:
    """Map MSAL / AADSTS error codes to human-readable German messages."""
    desc = error_description or ""
    if "AADSTS90002" in desc:
        return "Tenant nicht gefunden. Bitte Tenant-ID prüfen."
    if "AADSTS700016" in desc:
        return "App nicht gefunden. Bitte Client-ID prüfen."
    if "AADSTS7000215" in desc or "AADSTS7000222" in desc:
        return "Client-Secret ungültig oder abgelaufen."
    if "AADSTS650052" in desc:
        return "Admin-Zustimmung fehlt. Bitte API-Berechtigungen im Azure-Portal bestätigen."
    if "AADSTS53003" in desc:
        return "Zugriff durch Conditional Access verweigert."
    if "AADSTS70011" in desc:
        return "Ungültiger Scope. Bitte API-Berechtigungen der App prüfen."
    if "AADSTS700082" in desc:
        return "Refresh Token abgelaufen – bitte erneut authentifizieren."
    if error == "invalid_client":
        return "Authentifizierung fehlgeschlagen – Client-ID oder Secret ungültig."
    if error == "invalid_request":
        return "Ungültige Anfrage – Konfiguration prüfen."
    if error == "unauthorized_client":
        return "App ist nicht berechtigt, diesen Grant-Typ zu verwenden."
    snippet = desc[:150] if desc else error or "unbekannt"
    return f"Verbindungsfehler: {snippet}"


async def verify_azure_connection(
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> tuple[bool, str]:
    """Acquire a Graph token with the given credentials. Returns (ok, message)."""
    if not (tenant_id and client_id and client_secret):
        return False, "Bitte alle Felder ausfüllen (Tenant-ID, Client-ID, Secret)."
    if tenant_id in _PLACEHOLDER_VALUES or client_id in _PLACEHOLDER_VALUES:
        return False, "Bitte gültige Werte eintragen (keine Platzhalterwerte)."
    try:
        import msal  # noqa: PLC0415

        msal_app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        result = msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            return True, "Verbindung erfolgreich – Microsoft Graph erreichbar."
        error = result.get("error", "")
        desc = result.get("error_description", "")
        logger.warning("Azure verify failed: %s – %s", error, desc[:200])
        return False, _map_msal_error(error, desc)
    except OSError:
        return False, "Keine Verbindung zu Microsoft-Servern möglich."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Azure verify exception: %s", exc)
        return False, f"Unerwarteter Fehler: {exc}"


async def verify_smtp_connection(
    host: str,
    port: int,
    user: str,
    password: str,
    use_tls: bool,
) -> tuple[bool, str]:
    """Verify SMTP credentials without sending a mail. Returns (ok, message)."""
    if not host:
        return False, "Kein SMTP-Host konfiguriert."
    try:
        import aiosmtplib  # noqa: PLC0415

        smtp = aiosmtplib.SMTP(hostname=host, port=port, start_tls=use_tls)
        await smtp.connect()
        if user and password:
            await smtp.login(user, password)
        await smtp.quit()
        return True, f"SMTP-Verbindung zu {host}:{port} erfolgreich."
    except aiosmtplib.SMTPAuthenticationError:
        return False, "SMTP-Authentifizierung fehlgeschlagen – Benutzername oder Passwort prüfen."
    except aiosmtplib.SMTPConnectError as exc:
        return False, f"Verbindung zu {host}:{port} fehlgeschlagen: {exc}"
    except OSError as exc:
        return False, f"Netzwerkfehler: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("SMTP verify exception: %s", exc)
        return False, f"Unerwarteter Fehler: {exc}"
