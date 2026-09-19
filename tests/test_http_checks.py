"""Unit + route tests for HTTP health checks (app.http_check_client, admin routes,
and the combined monitoring dashboard). Network calls use httpx.MockTransport -
no real requests are made."""
import os

os.environ.setdefault("DISABLE_AUTH", "true")

import httpx
import pytest

from app.http_check_client import check_http_endpoint, get_http_check_severity


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_check_http_endpoint_up():
    def handler(request):
        return httpx.Response(200)

    result = await check_http_endpoint("https://example.com", transport=_transport(handler))
    assert result["is_up"] is True
    assert result["status_code"] == 200
    assert result["error_message"] is None
    assert result["response_time_ms"] >= 0


@pytest.mark.asyncio
async def test_check_http_endpoint_unexpected_status():
    def handler(request):
        return httpx.Response(500)

    result = await check_http_endpoint("https://example.com", transport=_transport(handler))
    assert result["is_up"] is False
    assert result["status_code"] == 500
    assert "500" in result["error_message"]


@pytest.mark.asyncio
async def test_check_http_endpoint_expected_status_override():
    def handler(request):
        return httpx.Response(204)

    result = await check_http_endpoint(
        "https://example.com", expected_status=204, transport=_transport(handler)
    )
    assert result["is_up"] is True


@pytest.mark.asyncio
async def test_check_http_endpoint_connection_failure():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    result = await check_http_endpoint("https://example.com", transport=_transport(handler))
    assert result["is_up"] is False
    assert result["status_code"] is None
    assert result["error_message"]


def test_get_http_check_severity():
    assert get_http_check_severity(is_up=True) == "low"
    assert get_http_check_severity(is_up=False) == "critical"


class TestHttpCheckAdminRoutes:
    """CRUD + dashboard routes, exercised through a lifespan-initialized TestClient
    so init_db() actually runs (unlike tests/test_admin_routes.py's module-level
    client, which skips lifespan and hits every route against an empty DB)."""

    def test_create_list_and_delete(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app, follow_redirects=False) as client:
            create = client.post(
                "/admin/http-checks/create",
                data={
                    "service_name": "Test API",
                    "http_url": "https://example.com/health",
                    "http_expected_status": "200",
                },
            )
            assert create.status_code == 303

            listing = client.get("/admin/http-checks")
            assert listing.status_code == 200
            assert "Test API" in listing.text

            dashboard = client.get("/admin/monitoring")
            assert dashboard.status_code == 200
            assert "Test API" in dashboard.text

            delete = client.post("/admin/http-checks/Test API/delete")
            assert delete.status_code == 303

            listing_after = client.get("/admin/http-checks")
            assert "Test API" not in listing_after.text

    def test_monitoring_dashboard_renders_certificates_too(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app, follow_redirects=False) as client:
            client.post(
                "/admin/certificates/create",
                data={"service_name": "Test Cert Service", "cert_hostname": "example.com"},
            )
            dashboard = client.get("/admin/monitoring")
            assert dashboard.status_code == 200
            assert "Test Cert Service" in dashboard.text
