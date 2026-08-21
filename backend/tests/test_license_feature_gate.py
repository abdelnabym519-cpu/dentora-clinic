import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.license.dependencies import require_license_feature
from app.core.license.service import license_manager


@pytest.mark.asyncio
async def test_ai_feature_allows_when_license_has_ai(monkeypatch):
    monkeypatch.setattr(settings, "LICENSE_ENFORCEMENT", True)

    async def fake_status(*, allow_refresh=True):
        return {
            "active": True,
            "features": ["core", "booking", "ai"],
        }

    monkeypatch.setattr(license_manager, "get_status", fake_status)

    dependency = require_license_feature("ai")

    await dependency()


@pytest.mark.asyncio
async def test_ai_feature_rejects_when_license_has_no_ai(monkeypatch):
    monkeypatch.setattr(settings, "LICENSE_ENFORCEMENT", True)

    async def fake_status(*, allow_refresh=True):
        return {
            "active": True,
            "features": ["core", "booking"],
        }

    monkeypatch.setattr(license_manager, "get_status", fake_status)

    dependency = require_license_feature("ai")

    with pytest.raises(HTTPException) as exc_info:
        await dependency()

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "feature_not_enabled"
    assert exc_info.value.detail["feature"] == "ai"


@pytest.mark.asyncio
async def test_ai_feature_rejects_inactive_license(monkeypatch):
    monkeypatch.setattr(settings, "LICENSE_ENFORCEMENT", True)

    async def fake_status(*, allow_refresh=True):
        return {
            "active": False,
            "features": ["core", "booking", "ai"],
        }

    monkeypatch.setattr(license_manager, "get_status", fake_status)

    dependency = require_license_feature("ai")

    with pytest.raises(HTTPException) as exc_info:
        await dependency()

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "license_inactive"


@pytest.mark.asyncio
async def test_ai_feature_is_not_enforced_in_development(monkeypatch):
    monkeypatch.setattr(settings, "LICENSE_ENFORCEMENT", False)

    async def should_not_be_called(*, allow_refresh=True):
        raise AssertionError("license manager should not be called")

    monkeypatch.setattr(
        license_manager,
        "get_status",
        should_not_be_called,
    )

    dependency = require_license_feature("ai")

    await dependency()
