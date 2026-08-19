from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.core.license import license_manager
from app.modules.booking import cloud_client
from app.modules.booking.cloud_client import BookingCloudError


def test_booking_cloud_configuration_has_safe_defaults() -> None:
    configured = Settings(
        DATABASE_URL="postgresql+asyncpg://synthetic:synthetic@localhost/test",
        SECRET_KEY="synthetic-test-key",
        _env_file=None,
    )

    assert configured.BOOKING_CLOUD_BASE_URL == ""
    assert configured.BOOKING_SYNC_HTTP_TIMEOUT_SECONDS == 10.0


def test_booking_cloud_factory_requires_explicit_base_url(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        cloud_client.settings,
        "BOOKING_CLOUD_BASE_URL",
        "",
    )

    with pytest.raises(
        BookingCloudError,
        match="base URL is not configured",
    ):
        cloud_client.build_booking_cloud_client()


def test_booking_cloud_factory_requires_positive_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        cloud_client.settings,
        "BOOKING_CLOUD_BASE_URL",
        "https://booking.example.com",
    )
    monkeypatch.setattr(
        cloud_client.settings,
        "BOOKING_SYNC_HTTP_TIMEOUT_SECONDS",
        0.0,
    )

    with pytest.raises(
        BookingCloudError,
        match="timeout must be positive",
    ):
        cloud_client.build_booking_cloud_client()


@pytest.mark.asyncio
async def test_booking_cloud_factory_uses_fresh_license_credential(
    monkeypatch,
) -> None:
    credentials = iter(
        [
            "synthetic-lease-one",
            "synthetic-lease-two",
        ]
    )
    seen_authorization = []

    async def credential_resolver() -> str:
        return next(credentials)

    def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(
            request.headers.get("Authorization")
        )

        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "requests": [],
                },
            },
        )

    monkeypatch.setattr(
        cloud_client.settings,
        "BOOKING_CLOUD_BASE_URL",
        "https://booking.example.com/",
    )
    monkeypatch.setattr(
        cloud_client.settings,
        "BOOKING_SYNC_HTTP_TIMEOUT_SECONDS",
        7.5,
    )
    monkeypatch.setattr(
        license_manager,
        "get_booking_sync_credential",
        credential_resolver,
    )

    client = cloud_client.build_booking_cloud_client(
        transport=httpx.MockTransport(handler),
    )

    await client.pull_requests()
    await client.pull_requests()

    assert client._base_url == "https://booking.example.com"
    assert client._timeout.connect == 7.5

    assert seen_authorization == [
        "Bearer synthetic-lease-one",
        "Bearer synthetic-lease-two",
    ]
