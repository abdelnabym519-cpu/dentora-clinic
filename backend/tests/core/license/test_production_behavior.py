from __future__ import annotations

from collections.abc import Callable

import pytest

from app.core.license import service as license_service
from app.core.license.service import LicenseManager, LicenseUnavailableError


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> LicenseManager:
    monkeypatch.setattr(license_service.settings, "LICENSE_ENFORCEMENT", True)
    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_SERVER_URL",
        "https://license.example.test",
    )
    monkeypatch.setattr(license_service.settings, "LICENSE_PUBLIC_KEY_B64", "configured")
    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_MACHINE_FINGERPRINT",
        "fingerprint-1",
    )
    instance = LicenseManager()
    monkeypatch.setattr(instance, "installation_id", lambda: "installation-1")
    return instance


def valid_payload(**overrides: object) -> dict:
    payload = {
        "product": "dentora",
        "v": 1,
        "installation_id": "installation-1",
        "fingerprint": "fingerprint-1",
        "customer_name": "Clinic",
        "plan": "production",
        "features": ["core", "booking"],
        "refresh_after": "2000-01-01T00:00:00+00:00",
        "valid_until": "2999-01-01T00:00:00+00:00",
        "license_expires_at": "2999-01-01T00:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def install_token_verifier(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
    resolver: Callable[[str], dict],
) -> None:
    monkeypatch.setattr(manager, "_verify_token", resolver)


def test_enforced_license_requires_machine_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_MACHINE_FINGERPRINT",
        "",
    )

    status = manager._status_from_state({})

    assert status["active"] is False
    assert status["state"] == "misconfigured"
    assert status["reason"] == "License service is not configured"


def test_malformed_signed_lease_timestamps_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    install_token_verifier(
        monkeypatch,
        manager,
        lambda token: valid_payload(valid_until="not-a-date"),
    )

    status = manager._status_from_state({"lease_token": "signed-lease"})

    assert status["active"] is False
    assert status["state"] == "invalid"
    assert status["reason"] == "License lease timestamps are invalid"


def test_malformed_signed_lease_features_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    install_token_verifier(
        monkeypatch,
        manager,
        lambda token: valid_payload(features="booking"),
    )

    status = manager._status_from_state({"lease_token": "signed-lease"})

    assert status["active"] is False
    assert status["state"] == "invalid"
    assert status["reason"] == "License lease features are invalid"


@pytest.mark.asyncio
async def test_activation_does_not_persist_invalid_server_lease(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    async def fake_server_post(path: str, payload: dict) -> dict:
        assert path == "/v1/activate"
        return {"lease_token": "invalid-server-lease"}

    monkeypatch.setattr(manager, "_server_post", fake_server_post)
    install_token_verifier(
        monkeypatch,
        manager,
        lambda token: valid_payload(fingerprint="other-machine"),
    )
    saved: list[dict] = []
    monkeypatch.setattr(manager, "_save_state", lambda state: saved.append(dict(state)))

    with pytest.raises(LicenseUnavailableError, match="License machine mismatch"):
        await manager.activate("DENTORA-LICENSE-KEY")

    assert saved == []


@pytest.mark.asyncio
async def test_refresh_keeps_previous_lease_when_server_returns_invalid_lease(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    async def fake_server_post(path: str, payload: dict) -> dict:
        assert path == "/v1/refresh"
        assert payload["lease_token"] == "current-lease"
        return {"lease_token": "invalid-refreshed-lease"}

    monkeypatch.setattr(manager, "_server_post", fake_server_post)

    def resolve(token: str) -> dict:
        if token == "current-lease":
            return valid_payload()
        return valid_payload(fingerprint="other-machine")

    install_token_verifier(monkeypatch, manager, resolve)
    saved: list[dict] = []
    monkeypatch.setattr(manager, "_save_state", lambda state: saved.append(dict(state)))

    with pytest.raises(LicenseUnavailableError, match="License machine mismatch"):
        await manager.refresh({"lease_token": "current-lease"})

    assert saved
    assert all(state["lease_token"] == "current-lease" for state in saved)


@pytest.mark.asyncio
async def test_server_outage_uses_only_still_valid_offline_lease(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    state = {"lease_token": "current-lease"}
    monkeypatch.setattr(manager, "_load_state", lambda: dict(state))
    install_token_verifier(monkeypatch, manager, lambda token: valid_payload())
    monkeypatch.setattr(manager, "_refresh_attempt_due", lambda current: True)

    async def unavailable_refresh(current: dict | None = None) -> dict:
        raise LicenseUnavailableError("offline")

    monkeypatch.setattr(manager, "refresh", unavailable_refresh)

    status = await manager.get_status(allow_refresh=True)

    assert status["active"] is True
    assert status["state"] == "active"
    assert status["reason"] == "Offline grace period"


def test_malformed_local_refresh_timestamp_retries_instead_of_crashing(
    manager: LicenseManager,
) -> None:
    assert manager._refresh_attempt_due({"last_refresh_attempt_at": "not-a-date"}) is True
