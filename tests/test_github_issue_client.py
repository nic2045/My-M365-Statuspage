"""Unit tests for app.github_issue_client - no real network access (httpx.MockTransport)."""
import httpx
import pytest

from app.github_issue_client import GitHubIssueError, create_issue


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_create_issue_returns_html_url():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer tok"
        assert request.url.path == "/repos/nic2045/My-M365-Statuspage/issues"
        return httpx.Response(201, json={"html_url": "https://github.com/nic2045/My-M365-Statuspage/issues/1"})

    url = await create_issue(
        repo="nic2045/My-M365-Statuspage",
        token="tok",
        title="[OpenBao] foo",
        body="body",
        labels=["openbao-request"],
        transport=_transport(handler),
    )
    assert url == "https://github.com/nic2045/My-M365-Statuspage/issues/1"


@pytest.mark.asyncio
async def test_create_issue_raises_on_http_error_status():
    def handler(request):
        return httpx.Response(403, json={"message": "GitHub access is not enabled"})

    with pytest.raises(GitHubIssueError):
        await create_issue(
            repo="nic2045/My-M365-Statuspage",
            token="tok",
            title="t",
            body="b",
            labels=[],
            transport=_transport(handler),
        )


@pytest.mark.asyncio
async def test_create_issue_raises_on_connection_failure():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(GitHubIssueError):
        await create_issue(
            repo="nic2045/My-M365-Statuspage",
            token="tok",
            title="t",
            body="b",
            labels=[],
            transport=_transport(handler),
        )
