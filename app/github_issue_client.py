"""Minimal async GitHub REST client: creates one issue.

Used by app.routers.openbao_request to file an OpenBao secret-access request
(see .github/ISSUE_TEMPLATE/openbao-secret-request.yml) on behalf of a
logged-in user who doesn't have (or doesn't want to use) a GitHub account -
same destination repo, same fields, so the Cloud Operator's process
(infra/openbao/README.md) never needs to know which path a request came in
through.
"""
from __future__ import annotations

import httpx

_API_BASE = "https://api.github.com"
_TIMEOUT = 15.0


class GitHubIssueError(RuntimeError):
    """Raised when filing the GitHub issue fails - message is user-facing."""


async def create_issue(
    *,
    repo: str,
    token: str,
    title: str,
    body: str,
    labels: list[str],
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Creates an issue in `repo` ("owner/name"). Returns the issue's HTML URL.

    -transport is a test-only hook (httpx.MockTransport) - production callers never pass
    it, so httpx uses its normal network transport.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
        try:
            response = await client.post(
                f"{_API_BASE}/repos/{repo}/issues",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"title": title, "body": body, "labels": labels},
            )
        except httpx.HTTPError as exc:
            raise GitHubIssueError(f"GitHub war nicht erreichbar: {exc}") from exc
    if response.status_code >= 400:
        raise GitHubIssueError(
            f"GitHub hat die Anfrage abgelehnt (HTTP {response.status_code}): {response.text[:200]}"
        )
    return response.json()["html_url"]
