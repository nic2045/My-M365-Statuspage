"""Route-level smoke tests for /openbao-request via Starlette's TestClient.

Uses DISABLE_AUTH (dev-mode auth bypass) instead of a real OIDC login, and
monkeypatches app.routers.openbao_request.create_issue instead of hitting
GitHub - this is about the route wiring and error/success rendering, not the
GitHub API itself (see test_github_issue_client.py for that).
"""
import asyncio

import pytest
from starlette.testclient import TestClient

import app.routers.openbao_request as openbao_request_module
from app.config import settings
from app.database import init_db
from app.main import app


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch):
    monkeypatch.setattr(settings, "DISABLE_AUTH", True)
    monkeypatch.setattr(settings, "DEBUG", True)  # non-Secure session cookie for plain-http TestClient
    monkeypatch.setattr(settings, "OPENBAO_REQUEST_GITHUB_TOKEN", "test-token")


@pytest.fixture
def client():
    # Deliberately NOT a context manager: `with TestClient(app) as c` runs the app's
    # lifespan (start_scheduler(), which immediately tries to poll Microsoft Graph with
    # whatever Azure creds are configured) - irrelevant to this route and slow/flaky in a
    # sandboxed test run. Plain instantiation skips lifespan entirely.
    asyncio.run(init_db())
    return TestClient(app, follow_redirects=False)


def test_form_renders(client):
    r = client.get("/openbao-request")
    assert r.status_code == 200
    assert 'name="app_name"' in r.text


def test_submit_success_shows_issue_url(client, monkeypatch):
    async def fake_create_issue(**kwargs):
        assert kwargs["repo"] == settings.OPENBAO_REQUEST_GITHUB_REPO
        assert "[OpenBao] foo-app" in kwargs["title"]
        return "https://github.com/nic2045/My-M365-Statuspage/issues/42"

    monkeypatch.setattr(openbao_request_module, "create_issue", fake_create_issue)

    r = client.post(
        "/openbao-request",
        data={
            "app_name": "foo-app",
            "secret_name": "bar-secret",
            "requested_by": "me",
            "justification": "testing",
            "token_period": "",
        },
    )
    assert r.status_code == 200
    assert "https://github.com/nic2045/My-M365-Statuspage/issues/42" in r.text


def test_submit_without_token_shows_error(client, monkeypatch):
    monkeypatch.setattr(settings, "OPENBAO_REQUEST_GITHUB_TOKEN", "")

    r = client.post(
        "/openbao-request",
        data={
            "app_name": "foo-app",
            "secret_name": "bar-secret",
            "requested_by": "me",
            "justification": "testing",
            "token_period": "",
        },
    )
    assert r.status_code == 200
    assert "OPENBAO_REQUEST_GITHUB_TOKEN" in r.text
