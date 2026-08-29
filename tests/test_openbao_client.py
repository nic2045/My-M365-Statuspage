"""Unit tests for app.openbao_client - no real network access (httpx.MockTransport)."""
import json

import httpx
import pytest

from app.openbao_client import OpenBaoUnreachableError, get_secret, is_reachable, set_secret

ADDRESS = "https://secrets-prod.pyur.com"
PATH = "secret/data/m365-statuspage/azure-client-secret"


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_is_reachable_true_on_200():
    def handler(request):
        return httpx.Response(200, json={"initialized": True})

    assert await is_reachable(ADDRESS, transport=_transport(handler)) is True


@pytest.mark.asyncio
async def test_is_reachable_true_on_sealed_503():
    """A non-200 HTTP response still means OpenBao itself answered - VPN is up."""

    def handler(request):
        return httpx.Response(503, json={"sealed": True})

    assert await is_reachable(ADDRESS, transport=_transport(handler)) is True


@pytest.mark.asyncio
async def test_is_reachable_false_on_connect_error():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    assert await is_reachable(ADDRESS, transport=_transport(handler)) is False


@pytest.mark.asyncio
async def test_get_secret_returns_data():
    def handler(request):
        assert request.headers["X-Vault-Token"] == "tok"
        return httpx.Response(200, json={"data": {"data": {"client_secret": "s3cr3t"}}})

    result = await get_secret(ADDRESS, "tok", PATH, transport=_transport(handler))
    assert result == {"client_secret": "s3cr3t"}


@pytest.mark.asyncio
async def test_get_secret_returns_none_on_404():
    def handler(request):
        return httpx.Response(404, json={"errors": []})

    result = await get_secret(ADDRESS, "tok", PATH, transport=_transport(handler))
    assert result is None


@pytest.mark.asyncio
async def test_get_secret_raises_on_connection_failure():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(OpenBaoUnreachableError):
        await get_secret(ADDRESS, "tok", PATH, transport=_transport(handler))


@pytest.mark.asyncio
async def test_get_secret_raises_on_permission_denied():
    def handler(request):
        return httpx.Response(403, json={"errors": ["permission denied"]})

    with pytest.raises(httpx.HTTPStatusError):
        await get_secret(ADDRESS, "tok", PATH, transport=_transport(handler))


@pytest.mark.asyncio
async def test_set_secret_posts_wrapped_data():
    captured = {}

    def handler(request):
        captured["body"] = request.read()
        return httpx.Response(200, json={"data": {"version": 2}})

    await set_secret(
        ADDRESS, "tok", PATH, {"client_secret": "new"}, transport=_transport(handler)
    )
    assert json.loads(captured["body"]) == {"data": {"client_secret": "new"}}
