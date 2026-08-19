from __future__ import annotations

import pytest

from app.core.license.service import (
    LicenseManager,
    LicenseRejectedError,
)


@pytest.fixture
def manager() -> LicenseManager:
    return LicenseManager()


@pytest.mark.asyncio
async def test_booking_sync_credential_returns_current_signed_lease(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    token = "signed-booking-lease"

    async def fake_status(*, allow_refresh: bool = True) -> dict:
        assert allow_refresh is True
        return {
            "active": True,
            "features": ["core", "booking"],
        }

    monkeypatch.setattr(
        manager,
        "get_status",
        fake_status,
    )

    monkeypatch.setattr(
        manager,
        "_load_state",
        lambda: {
            "lease_token": token,
        },
    )

    monkeypatch.setattr(
        manager,
        "_verify_token",
        lambda value: {
            "installation_id": "installation-1",
            "fingerprint": "fingerprint-1",
        },
    )

    monkeypatch.setattr(
        manager,
        "installation_id",
        lambda: "installation-1",
    )

    from app.core.license import service as license_service

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_ENFORCEMENT",
        True,
    )

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_MACHINE_FINGERPRINT",
        "fingerprint-1",
    )

    credential = await manager.get_booking_sync_credential()

    assert credential == token


@pytest.mark.asyncio
async def test_booking_sync_credential_requires_booking_feature(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    async def fake_status(*, allow_refresh: bool = True) -> dict:
        assert allow_refresh is True
        return {
            "active": True,
            "features": ["core"],
        }

    monkeypatch.setattr(
        manager,
        "get_status",
        fake_status,
    )

    from app.core.license import service as license_service

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_ENFORCEMENT",
        True,
    )

    with pytest.raises(
        LicenseRejectedError,
        match="Booking feature is not enabled",
    ):
        await manager.get_booking_sync_credential()


@pytest.mark.asyncio
async def test_booking_sync_credential_requires_active_license(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    async def fake_status(*, allow_refresh: bool = True) -> dict:
        assert allow_refresh is True
        return {
            "active": False,
            "reason": "License subscription has expired",
            "features": ["core", "booking"],
        }

    monkeypatch.setattr(
        manager,
        "get_status",
        fake_status,
    )

    from app.core.license import service as license_service

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_ENFORCEMENT",
        True,
    )

    with pytest.raises(
        LicenseRejectedError,
        match="License subscription has expired",
    ):
        await manager.get_booking_sync_credential()



@pytest.mark.asyncio
async def test_booking_sync_credential_requires_license_enforcement(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    from app.core.license import service as license_service

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_ENFORCEMENT",
        False,
    )

    with pytest.raises(
        Exception,
        match="Booking sync credential is only available for licensed clients",
    ):
        await manager.get_booking_sync_credential()


@pytest.mark.asyncio
async def test_booking_sync_credential_requires_installed_lease(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    async def fake_status(*, allow_refresh: bool = True) -> dict:
        assert allow_refresh is True
        return {
            "active": True,
            "features": ["booking"],
        }

    monkeypatch.setattr(manager, "get_status", fake_status)
    monkeypatch.setattr(manager, "_load_state", lambda: {})

    from app.core.license import service as license_service

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_ENFORCEMENT",
        True,
    )

    with pytest.raises(
        Exception,
        match="No license lease is installed",
    ):
        await manager.get_booking_sync_credential()


@pytest.mark.asyncio
async def test_booking_sync_credential_rejects_installation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    async def fake_status(*, allow_refresh: bool = True) -> dict:
        assert allow_refresh is True
        return {
            "active": True,
            "features": ["booking"],
        }

    monkeypatch.setattr(manager, "get_status", fake_status)
    monkeypatch.setattr(
        manager,
        "_load_state",
        lambda: {"lease_token": "signed-booking-lease"},
    )
    monkeypatch.setattr(
        manager,
        "_verify_token",
        lambda value: {
            "installation_id": "other-installation",
            "fingerprint": "fingerprint-1",
        },
    )
    monkeypatch.setattr(
        manager,
        "installation_id",
        lambda: "installation-1",
    )

    from app.core.license import service as license_service

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_ENFORCEMENT",
        True,
    )
    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_MACHINE_FINGERPRINT",
        "fingerprint-1",
    )

    with pytest.raises(
        Exception,
        match="License installation mismatch",
    ):
        await manager.get_booking_sync_credential()


@pytest.mark.asyncio
async def test_booking_sync_credential_rejects_machine_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    manager: LicenseManager,
) -> None:
    async def fake_status(*, allow_refresh: bool = True) -> dict:
        assert allow_refresh is True
        return {
            "active": True,
            "features": ["booking"],
        }

    monkeypatch.setattr(manager, "get_status", fake_status)
    monkeypatch.setattr(
        manager,
        "_load_state",
        lambda: {"lease_token": "signed-booking-lease"},
    )
    monkeypatch.setattr(
        manager,
        "_verify_token",
        lambda value: {
            "installation_id": "installation-1",
            "fingerprint": "other-fingerprint",
        },
    )
    monkeypatch.setattr(
        manager,
        "installation_id",
        lambda: "installation-1",
    )

    from app.core.license import service as license_service

    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_ENFORCEMENT",
        True,
    )
    monkeypatch.setattr(
        license_service.settings,
        "LICENSE_MACHINE_FINGERPRINT",
        "fingerprint-1",
    )

    with pytest.raises(
        Exception,
        match="License machine mismatch",
    ):
        await manager.get_booking_sync_credential()
