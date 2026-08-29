"""Unit tests for app.azure_secret_manager's get-or-rotate orchestration logic.

Mocks at the module boundary (is_reachable/get_secret/set_secret/_rotate_client_secret/
save_azure_settings) rather than hitting real OpenBao, Microsoft Graph, or a DB - this
covers the decision logic (cache vs. rotate, error surfacing), not the Graph/OpenBao wire
formats themselves (those can't be verified without a real tenant/OpenBao instance - see
docs/README caveats).
"""
from datetime import UTC, datetime, timedelta

import pytest

from app import azure_secret_manager as mgr
from app.azure_secret_manager import AzureSecretSyncError, _NewSecret

TENANT_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"


class _FakeAsyncFn:
    """Simple async-callable recorder for monkeypatching module-level async functions."""

    def __init__(self, return_value=None, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.side_effect is not None:
            raise self.side_effect
        return self.return_value


@pytest.fixture(autouse=True)
def _openbao_settings(monkeypatch):
    monkeypatch.setattr(mgr.settings, "OPENBAO_ADDR", "https://secrets-prod.pyur.com")
    monkeypatch.setattr(mgr.settings, "OPENBAO_SECRET_PATH", "secret/data/test/azure")
    monkeypatch.setattr(mgr.settings, "OPENBAO_TOKEN", "test-token")
    monkeypatch.setattr(mgr.settings, "OPENBAO_RENEWAL_THRESHOLD_DAYS", 30)


@pytest.mark.asyncio
async def test_raises_when_openbao_unreachable(monkeypatch):
    monkeypatch.setattr(mgr, "is_reachable", _FakeAsyncFn(return_value=False))

    with pytest.raises(AzureSecretSyncError, match="VPN"):
        await mgr.get_or_rotate_client_secret(db=None, tenant_id=TENANT_ID, client_id=CLIENT_ID)


@pytest.mark.asyncio
async def test_uses_cached_secret_when_still_valid(monkeypatch):
    far_future = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    stored = {"client_secret": "cached-secret", "expires_on": far_future, "key_id": "kid-1"}

    monkeypatch.setattr(mgr, "is_reachable", _FakeAsyncFn(return_value=True))
    monkeypatch.setattr(mgr, "get_secret", _FakeAsyncFn(return_value=stored))
    set_secret_fn = _FakeAsyncFn()
    monkeypatch.setattr(mgr, "set_secret", set_secret_fn)
    rotate_fn = _FakeAsyncFn()
    monkeypatch.setattr(mgr, "_rotate_client_secret", rotate_fn)
    save_fn = _FakeAsyncFn()
    monkeypatch.setattr(mgr, "save_azure_settings", save_fn)

    result = await mgr.get_or_rotate_client_secret(
        db=None, tenant_id=TENANT_ID, client_id=CLIENT_ID
    )

    assert result.client_secret == "cached-secret"
    assert result.rotated is False
    assert rotate_fn.calls == []  # no Graph call for a still-valid secret
    assert set_secret_fn.calls == []  # nothing new to persist to OpenBao
    assert save_fn.calls[0][1]["client_secret"] == "cached-secret"


@pytest.mark.asyncio
async def test_rotates_when_nothing_stored_yet(monkeypatch):
    new_secret = _NewSecret(client_secret="fresh-secret", key_id="kid-2", expires_on="2027-01-01")

    monkeypatch.setattr(mgr, "is_reachable", _FakeAsyncFn(return_value=True))
    monkeypatch.setattr(mgr, "get_secret", _FakeAsyncFn(return_value=None))
    set_secret_fn = _FakeAsyncFn()
    monkeypatch.setattr(mgr, "set_secret", set_secret_fn)
    monkeypatch.setattr(mgr, "_rotate_client_secret", _FakeAsyncFn(return_value=new_secret))
    save_fn = _FakeAsyncFn()
    monkeypatch.setattr(mgr, "save_azure_settings", save_fn)

    result = await mgr.get_or_rotate_client_secret(
        db=None, tenant_id=TENANT_ID, client_id=CLIENT_ID
    )

    assert result.client_secret == "fresh-secret"
    assert result.rotated is True
    assert set_secret_fn.calls[0][0][3]["client_secret"] == "fresh-secret"
    assert save_fn.calls[0][1]["client_secret"] == "fresh-secret"


@pytest.mark.asyncio
async def test_rotates_when_expiring_soon(monkeypatch):
    soon = (datetime.now(UTC) + timedelta(days=5)).isoformat()  # inside the 30-day threshold
    stored = {"client_secret": "old-secret", "expires_on": soon, "key_id": "kid-old"}
    new_secret = _NewSecret(client_secret="new-secret", key_id="kid-new", expires_on="2027-01-01")

    monkeypatch.setattr(mgr, "is_reachable", _FakeAsyncFn(return_value=True))
    monkeypatch.setattr(mgr, "get_secret", _FakeAsyncFn(return_value=stored))
    monkeypatch.setattr(mgr, "set_secret", _FakeAsyncFn())
    rotate_fn = _FakeAsyncFn(return_value=new_secret)
    monkeypatch.setattr(mgr, "_rotate_client_secret", rotate_fn)
    monkeypatch.setattr(mgr, "save_azure_settings", _FakeAsyncFn())

    result = await mgr.get_or_rotate_client_secret(
        db=None, tenant_id=TENANT_ID, client_id=CLIENT_ID
    )

    assert result.rotated is True
    # previous_key_id was passed through so the old credential can be cleaned up
    assert rotate_fn.calls[0][1]["previous_key_id"] == "kid-old"


@pytest.mark.asyncio
async def test_force_rotates_even_when_still_valid(monkeypatch):
    far_future = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    stored = {"client_secret": "old-secret", "expires_on": far_future, "key_id": "kid-old"}
    new_secret = _NewSecret(client_secret="forced-secret", key_id="kid-new", expires_on="2027-01-01")

    monkeypatch.setattr(mgr, "is_reachable", _FakeAsyncFn(return_value=True))
    monkeypatch.setattr(mgr, "get_secret", _FakeAsyncFn(return_value=stored))
    monkeypatch.setattr(mgr, "set_secret", _FakeAsyncFn())
    monkeypatch.setattr(mgr, "_rotate_client_secret", _FakeAsyncFn(return_value=new_secret))
    monkeypatch.setattr(mgr, "save_azure_settings", _FakeAsyncFn())

    result = await mgr.get_or_rotate_client_secret(
        db=None, tenant_id=TENANT_ID, client_id=CLIENT_ID, force=True
    )

    assert result.client_secret == "forced-secret"
    assert result.rotated is True
