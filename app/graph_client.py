import asyncio
import logging

import httpx
import msal

from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_msal_app: msal.ConfidentialClientApplication | None = None


def _get_msal_app() -> msal.ConfidentialClientApplication:
    global _msal_app
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=settings.AZURE_CLIENT_ID,
            client_credential=settings.AZURE_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}",
        )
    return _msal_app


async def _get_access_token() -> str:
    app = _get_msal_app()
    # MSAL token acquisition is synchronous; run in thread to avoid blocking event loop
    result = await asyncio.to_thread(
        app.acquire_token_for_client,
        ["https://graph.microsoft.com/.default"],
    )
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown"))
        raise RuntimeError(f"MSAL token acquisition failed: {error}")
    return result["access_token"]


async def fetch_health_overviews() -> list[dict]:
    """Returns healthOverview objects for all services."""
    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GRAPH_BASE}/admin/serviceAnnouncement/healthOverviews",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json().get("value", [])


async def fetch_active_issues() -> list[dict]:
    """Returns all unresolved service health issues, with posts expanded."""
    token = await _get_access_token()
    all_issues: list[dict] = []
    url = f"{GRAPH_BASE}/admin/serviceAnnouncement/issues"
    params = {
        "$filter": "isResolved eq false",
        "$expand": "posts",
        "$top": "100",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params if url == f"{GRAPH_BASE}/admin/serviceAnnouncement/issues" else None,
            )
            resp.raise_for_status()
            data = resp.json()
            all_issues.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
    return all_issues
