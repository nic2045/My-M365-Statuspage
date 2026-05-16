"""HTTP integration tests against a running Docker container.

The container must already be running before these tests execute.
Configure via environment variables:
  CONTAINER_URL  – base URL of the container  (default: http://localhost:8000)
  EMBED_API_KEY  – embed token set on the container (default: test-embed-key-ci)
"""
import os

import httpx
import pytest

BASE_URL = os.getenv("CONTAINER_URL", "http://localhost:8000")
EMBED_KEY = os.getenv("EMBED_API_KEY", "test-embed-key-ci")


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, follow_redirects=False, timeout=10) as c:
        yield c


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_200(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── Auth protection ───────────────────────────────────────────────────────────

def test_root_redirects_to_login(client):
    r = client.get("/")
    assert r.status_code == 302
    location = r.headers.get("location", "")
    assert "auth/login" in location.lower(), f"unexpected Location: {location}"


def test_api_status_no_auth_redirects(client):
    r = client.get("/api/v1/status")
    assert r.status_code == 302


# ── Embed: token access ───────────────────────────────────────────────────────

def test_embed_no_token_401(client):
    r = client.get("/embed")
    assert r.status_code == 401


def test_embed_wrong_token_401(client):
    r = client.get("/embed", params={"token": "definitely-not-the-right-key"})
    assert r.status_code == 401


def test_embed_valid_token_200(client):
    r = client.get("/embed", params={"token": EMBED_KEY})
    assert r.status_code == 200


def test_embed_returns_html(client):
    r = client.get("/embed", params={"token": EMBED_KEY})
    assert "text/html" in r.headers.get("content-type", "")


# ── Embed: iframe-safety headers ──────────────────────────────────────────────

def test_embed_no_x_frame_options(client):
    """X-Frame-Options must be absent so Confluence/Typo3 iframes work."""
    r = client.get("/embed", params={"token": EMBED_KEY})
    assert "x-frame-options" not in r.headers, (
        f"X-Frame-Options present – blocks iframe embedding: {r.headers['x-frame-options']}"
    )


def test_embed_csp_allows_framing(client):
    """Content-Security-Policy should allow framing from any origin."""
    r = client.get("/embed", params={"token": EMBED_KEY})
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp, f"frame-ancestors missing from CSP: {csp}"
