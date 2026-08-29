"""Minimal async OpenBao (HashiCorp Vault-API-compatible) client.

Talks to OpenBao's plain HTTP KV v2 API via httpx - no `bao` CLI or Vault SDK
dependency needed. Used by app.azure_secret_manager to store/read the Entra ID
app registration's client secret instead of only ever persisting it in this
app's own database.

OpenBao is reachable ONLY over the org VPN, not continuously - reachability is
checked separately (is_reachable) so callers can surface "connect the VPN and
try again" instead of a raw connection-error traceback.
"""
from __future__ import annotations

import httpx

_REQUEST_TIMEOUT = 10.0


class OpenBaoUnreachableError(RuntimeError):
    """OpenBao could not be reached at all (VPN down, DNS failure, timeout)."""


async def is_reachable(address: str, *, transport: httpx.BaseTransport | None = None) -> bool:
    """True once OpenBao responds to ANY HTTP status - not just 200.

    /v1/sys/health returns non-200 for perfectly reachable-but-not-ready states
    (503 sealed, 429 standby, 501 uninitialized) - those still mean the VPN is
    up and OpenBao is there. Only a connection-level failure (no HTTP response
    at all) means "not reachable".

    -transport is a test-only hook (httpx.MockTransport) - production callers
    never pass it, so httpx uses its normal network transport.
    """
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, transport=transport) as client:
            await client.get(f"{address}/v1/sys/health")
        return True
    except httpx.HTTPError:
        return False


async def get_secret(
    address: str, token: str, path: str, *, transport: httpx.BaseTransport | None = None
) -> dict | None:
    """Read the current version of a KV v2 secret. None if nothing is stored yet (404)."""
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, transport=transport) as client:
        try:
            response = await client.get(f"{address}/v1/{path}", headers={"X-Vault-Token": token})
        except httpx.HTTPError as exc:
            raise OpenBaoUnreachableError(f"OpenBao request failed: {exc}") from exc
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()["data"]["data"]


async def set_secret(
    address: str,
    token: str,
    path: str,
    data: dict,
    *,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Write a new KV v2 version. OpenBao keeps prior versions itself - never overwritten here."""
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, transport=transport) as client:
        try:
            response = await client.post(
                f"{address}/v1/{path}",
                headers={"X-Vault-Token": token},
                json={"data": data},
            )
        except httpx.HTTPError as exc:
            raise OpenBaoUnreachableError(f"OpenBao request failed: {exc}") from exc
    response.raise_for_status()
