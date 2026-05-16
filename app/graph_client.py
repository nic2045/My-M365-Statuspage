import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

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


async def fetch_issues_since(service_name: str, days: int = 90) -> list[dict]:
    """Fetch all issues (including resolved) for a service over the past N days, for backfill."""
    token = await _get_access_token()
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    name_encoded = quote(service_name, safe="")
    base_url = (
        f"{GRAPH_BASE}/admin/serviceAnnouncement/issues"
        f"?$filter=service eq '{name_encoded}' and startDateTime ge {since}"
        f"&$select=id,service,classification,startDateTime,endDateTime,lastModifiedDateTime,isResolved,severity"
        f"&$top=100"
    )
    all_issues: list[dict] = []
    async with httpx.AsyncClient(timeout=60) as client:
        url: str | None = base_url
        while url:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()
            all_issues.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
    return all_issues


async def fetch_recently_resolved_issues(days: int = 30) -> list[dict]:
    """Returns resolved issues that started within the past N days.

    The Graph API does not support filtering on lastModifiedDateTime, so we
    filter on startDateTime (a supported property) and accept that a small
    number of long-running incidents resolved just inside the window may be
    missed while keeping the query valid.
    """
    token = await _get_access_token()
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    base_url = (
        f"{GRAPH_BASE}/admin/serviceAnnouncement/issues"
        f"?$filter=isResolved eq true and startDateTime ge {since}"
        f"&$expand=posts"
        f"&$top=100"
    )
    all_issues: list[dict] = []
    async with httpx.AsyncClient(timeout=60) as client:
        url: str | None = base_url
        while url:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()
            all_issues.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
    return all_issues


async def fetch_active_issues() -> list[dict]:
    """Returns all unresolved service health issues, with posts expanded."""
    token = await _get_access_token()
    all_issues: list[dict] = []
    # OData $ parameters must NOT be percent-encoded; embed them in the URL
    # directly so httpx leaves them as-is instead of encoding $ → %24.
    base_url = (
        f"{GRAPH_BASE}/admin/serviceAnnouncement/issues"
        "?$filter=isResolved eq false&$expand=posts&$top=100"
    )
    url: str | None = base_url
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            all_issues.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
    return all_issues
