"""Get-or-rotate the Entra ID app registration's client secret via OpenBao.

Lifecycle:
  1. Read the current secret from OpenBao (KV v2 - see app.openbao_client).
  2. Still valid (further than OPENBAO_RENEWAL_THRESHOLD_DAYS from expiry) and
     not forced -> use it as-is, no Microsoft Graph calls at all.
  3. Missing / expiring soon / forced -> rotate: create a new client secret on
     the app registration via Microsoft Graph (addPassword - the only way to
     ever see a secret's plaintext; an existing one can only be queried as
     metadata afterwards), store it in OpenBao, then remove the previous
     credential so the app registration doesn't accumulate old secrets.
  4. Either way, persist the resulting secret into this app's own settings
     (app_settings.save_azure_settings) so graph_client.py/auth.py/
     notifications.py keep working unchanged - they only ever read the
     effective secret via app_settings.get_azure_settings().

Rotating needs an access token with Application.ReadWrite.All on the app
registration - a higher privilege than this app's own day-to-day
ServiceHealth.Read.All. AZURE_MGMT_* settings (falling back to the AZURE_*
ones - see app/config.py) let that be a separate, narrower-scoped credential
instead of over-privileging the app's main one; either way it's only needed
on the rotate path, never for reading an already-valid secret out of OpenBao.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import msal
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import save_azure_settings
from app.config import settings
from app.openbao_client import OpenBaoUnreachableError, get_secret, is_reachable, set_secret

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_GRAPH_TIMEOUT = 15.0


class AzureSecretSyncError(RuntimeError):
    """Any failure in get_or_rotate_client_secret - message is meant to be user-facing."""


@dataclass
class SecretSyncResult:
    client_secret: str
    rotated: bool
    expires_on: str


@dataclass
class _NewSecret:
    client_secret: str
    key_id: str
    expires_on: str


async def get_or_rotate_client_secret(
    db: AsyncSession,
    *,
    tenant_id: str,
    client_id: str,
    force: bool = False,
) -> SecretSyncResult:
    """Get the effective client secret from OpenBao, rotating it first if needed.

    Always writes the result into this app's Azure settings (DB), so callers
    just need to re-read app_settings.get_azure_settings() afterwards - or use
    the returned client_secret directly.
    """
    address = settings.OPENBAO_ADDR
    if not await is_reachable(address):
        raise AzureSecretSyncError(
            f"OpenBao ({address}) ist nicht erreichbar - vermutlich ist die VPN-Verbindung "
            "nicht aktiv. VPN verbinden und erneut versuchen."
        )
    if not settings.OPENBAO_TOKEN:
        raise AzureSecretSyncError("OPENBAO_TOKEN ist nicht gesetzt.")

    path = settings.OPENBAO_SECRET_PATH
    try:
        stored = await get_secret(address, settings.OPENBAO_TOKEN, path)
    except OpenBaoUnreachableError as exc:
        raise AzureSecretSyncError(str(exc)) from exc

    needs_rotation = force or not stored or not stored.get("expires_on")
    if not needs_rotation:
        expires_on = datetime.fromisoformat(stored["expires_on"])
        needs_rotation = expires_on < datetime.now(UTC) + timedelta(
            days=settings.OPENBAO_RENEWAL_THRESHOLD_DAYS
        )

    if not needs_rotation:
        logger.info("Using cached OpenBao secret (valid until %s).", stored["expires_on"])
        await save_azure_settings(
            db, tenant_id=tenant_id, client_id=client_id, client_secret=stored["client_secret"]
        )
        return SecretSyncResult(
            client_secret=stored["client_secret"], rotated=False, expires_on=stored["expires_on"]
        )

    new_secret = await _rotate_client_secret(
        client_id=client_id, previous_key_id=(stored or {}).get("key_id")
    )
    try:
        await set_secret(
            address,
            settings.OPENBAO_TOKEN,
            path,
            {
                "client_id": client_id,
                "tenant_id": tenant_id,
                "client_secret": new_secret.client_secret,
                "key_id": new_secret.key_id,
                "expires_on": new_secret.expires_on,
            },
        )
    except OpenBaoUnreachableError as exc:
        raise AzureSecretSyncError(str(exc)) from exc

    logger.info("Rotated Azure client secret via Graph (expires %s).", new_secret.expires_on)
    await save_azure_settings(
        db, tenant_id=tenant_id, client_id=client_id, client_secret=new_secret.client_secret
    )
    return SecretSyncResult(
        client_secret=new_secret.client_secret, rotated=True, expires_on=new_secret.expires_on
    )


async def _get_mgmt_access_token() -> str:
    mgmt_tenant = settings.AZURE_MGMT_TENANT_ID or settings.AZURE_TENANT_ID
    mgmt_client = settings.AZURE_MGMT_CLIENT_ID or settings.AZURE_CLIENT_ID
    mgmt_secret = settings.AZURE_MGMT_CLIENT_SECRET or settings.AZURE_CLIENT_SECRET

    app = msal.ConfidentialClientApplication(
        client_id=mgmt_client,
        client_credential=mgmt_secret,
        authority=f"https://login.microsoftonline.com/{mgmt_tenant}",
    )
    # MSAL token acquisition is synchronous - run in a thread, same as graph_client.py.
    result = await asyncio.to_thread(
        app.acquire_token_for_client, ["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown"))
        raise AzureSecretSyncError(
            "Konnte kein Graph-Token für die Secret-Rotation holen "
            f"({error[:200]}). Braucht eine App-Registrierung mit "
            "Application.ReadWrite.All - siehe AZURE_MGMT_* in .env.example."
        )
    return result["access_token"]


async def _rotate_client_secret(*, client_id: str, previous_key_id: str | None) -> _NewSecret:
    token = await _get_mgmt_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=_GRAPH_TIMEOUT) as client:
        lookup = await client.get(
            f"{_GRAPH_BASE}/applications",
            headers=headers,
            params={"$filter": f"appId eq '{client_id}'"},
        )
        lookup.raise_for_status()
        apps = lookup.json().get("value", [])
        if not apps:
            raise AzureSecretSyncError(
                f"Keine Entra-ID-App-Registrierung für ClientId '{client_id}' gefunden."
            )
        app_object_id = apps[0]["id"]

        end_date_time = datetime.now(UTC) + timedelta(
            days=settings.OPENBAO_NEW_SECRET_LIFETIME_DAYS
        )
        created_resp = await client.post(
            f"{_GRAPH_BASE}/applications/{app_object_id}/addPassword",
            headers=headers,
            json={
                "passwordCredential": {
                    "displayName": f"openbao-managed-{datetime.now(UTC):%Y%m%d-%H%M%S}",
                    "endDateTime": end_date_time.isoformat(),
                }
            },
        )
        created_resp.raise_for_status()
        created = created_resp.json()

        if previous_key_id and previous_key_id != created["keyId"]:
            remove_resp = await client.post(
                f"{_GRAPH_BASE}/applications/{app_object_id}/removePassword",
                headers=headers,
                json={"keyId": previous_key_id},
            )
            if remove_resp.status_code >= 400:
                logger.warning(
                    "Could not remove previous client secret (keyId %s) from app %s: %s",
                    previous_key_id,
                    app_object_id,
                    remove_resp.text[:200],
                )

    return _NewSecret(
        client_secret=created["secretText"],
        key_id=created["keyId"],
        expires_on=created["endDateTime"],
    )
