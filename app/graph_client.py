import asyncio
import logging
from datetime import datetime, timedelta

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


async def _attach_posts(
    client: httpx.AsyncClient,
    token: str,
    issues: list[dict],
) -> None:
    """Fetch posts for each issue via the dedicated posts sub-resource and attach in-place.

    $expand=posts is not reliably supported on the issues collection endpoint with $filter,
    so we fetch posts individually per issue. Errors per-issue are suppressed so a single
    unavailable issue does not abort the whole batch.
    """
    headers = {"Authorization": f"Bearer {token}"}
    for issue in issues:
        issue_id = issue.get("id", "")
        if not issue_id:
            issue.setdefault("posts", [])
            continue
        try:
            resp = await client.get(
                f"{GRAPH_BASE}/admin/serviceAnnouncement/issues/{issue_id}/posts",
                headers=headers,
            )
            issue["posts"] = resp.json().get("value", []) if resp.status_code == 200 else []
        except Exception:
            issue["posts"] = []


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
    base_url = (
        f"{GRAPH_BASE}/admin/serviceAnnouncement/issues"
        f"?$filter=service eq '{service_name}' and startDateTime ge {since}"
        f"&$select=id,service,title,classification,status,startDateTime,endDateTime,lastModifiedDateTime,isResolved,severity,impactDescription"
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
    """Returns resolved issues that started within the past N days, with posts.

    The Graph API does not support filtering on lastModifiedDateTime, so we
    filter on startDateTime (a supported property). Posts are fetched per-issue
    because $expand=posts is not supported on the collection endpoint with $filter.
    """
    token = await _get_access_token()
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    base_url = (
        f"{GRAPH_BASE}/admin/serviceAnnouncement/issues"
        f"?$filter=isResolved eq true and startDateTime ge {since}"
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
        await _attach_posts(client, token, all_issues)
    return all_issues


async def fetch_active_issues() -> list[dict]:
    """Returns all unresolved service health issues, with posts.

    Posts are fetched per-issue because $expand=posts is not supported on the
    collection endpoint when combined with $filter.
    """
    token = await _get_access_token()
    all_issues: list[dict] = []
    base_url = (
        f"{GRAPH_BASE}/admin/serviceAnnouncement/issues"
        "?$filter=isResolved eq false&$top=100"
    )
    url: str | None = base_url
    async with httpx.AsyncClient(timeout=60) as client:
        while url:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            all_issues.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        await _attach_posts(client, token, all_issues)
    return all_issues
