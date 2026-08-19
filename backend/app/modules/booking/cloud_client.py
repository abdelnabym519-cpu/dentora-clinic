"""Outbound HTTPS client for DentalPin public booking cloud sync."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.core.license import license_manager

BookingCredentialResolver = Callable[[], Awaitable[str]]


class BookingCloudError(RuntimeError):
    """Base error for outbound booking cloud synchronization."""


class BookingCloudAuthError(BookingCloudError):
    """Booking cloud rejected the current synchronization credential."""


class BookingCloudTransientError(BookingCloudError):
    """Temporary booking cloud failure that should be retried later."""


class BookingCloudProtocolError(BookingCloudError):
    """Booking cloud returned an unexpected successful response."""


class BookingCloudClient:
    """Small authenticated client for the booking cloud sync API.

    Every request resolves a fresh signed commercial lease so a refreshed
    credential is picked up without recreating the client.
    """

    def __init__(
        self,
        *,
        base_url: str,
        credential_resolver: BookingCredentialResolver,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")

        if not normalized_base_url:
            raise ValueError("Booking cloud base URL is required")

        if not normalized_base_url.startswith("https://"):
            raise ValueError("Booking cloud base URL must use HTTPS")

        self._base_url = normalized_base_url
        self._credential_resolver = credential_resolver
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)

    async def _authorization_headers(self) -> dict[str, str]:
        token = (await self._credential_resolver()).strip()

        if not token:
            raise BookingCloudError("Booking sync credential is empty")

        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = await self._authorization_headers()

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    headers=headers,
                    json=json_body,
                )
        except httpx.RequestError as exc:
            raise BookingCloudTransientError(
                "Booking cloud request failed temporarily"
            ) from exc

        if response.status_code in {401, 403}:
            raise BookingCloudAuthError(
                "Booking cloud rejected the synchronization credential"
            )

        if 500 <= response.status_code <= 599:
            raise BookingCloudTransientError(
                "Booking cloud is temporarily unavailable"
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BookingCloudError(
                "Booking cloud rejected the synchronization request"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BookingCloudProtocolError(
                "Booking cloud returned invalid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise BookingCloudProtocolError(
                "Booking cloud returned an invalid response"
            )

        if payload.get("ok") is not True:
            raise BookingCloudProtocolError(
                "Booking cloud returned an unsuccessful response"
            )

        return payload

    async def pull_requests(self) -> list[dict[str, Any]]:
        """Pull unresolved requests assigned to this licensed installation."""

        payload = await self._request(
            "GET",
            "/api/v1/sync/requests",
        )

        data = payload.get("data")

        if not isinstance(data, dict):
            raise BookingCloudProtocolError(
                "Booking cloud response has no data object"
            )

        requests = data.get("requests")

        if not isinstance(requests, list):
            raise BookingCloudProtocolError(
                "Booking cloud response has no requests list"
            )

        if not all(isinstance(item, dict) for item in requests):
            raise BookingCloudProtocolError(
                "Booking cloud returned an invalid booking request"
            )

        return requests

    async def resolve_request(
        self,
        request_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Send the final local acceptance/rejection result to the cloud."""

        normalized_request_id = request_id.strip()

        if not normalized_request_id:
            raise ValueError("Booking request ID is required")

        payload = await self._request(
            "POST",
            (
                "/api/v1/sync/requests/"
                f"{quote(normalized_request_id, safe='')}/result"
            ),
            json_body=result,
        )

        data = payload.get("data")

        if not isinstance(data, dict):
            raise BookingCloudProtocolError(
                "Booking cloud response has no data object"
            )

        return data


def build_booking_cloud_client(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BookingCloudClient:
    """Build the licensed outbound booking cloud client."""

    base_url = settings.BOOKING_CLOUD_BASE_URL.strip()

    if not base_url:
        raise BookingCloudError(
            "Booking cloud base URL is not configured"
        )

    timeout_seconds = settings.BOOKING_SYNC_HTTP_TIMEOUT_SECONDS

    if timeout_seconds <= 0:
        raise BookingCloudError(
            "Booking cloud HTTP timeout must be positive"
        )

    return BookingCloudClient(
        base_url=base_url,
        credential_resolver=license_manager.get_booking_sync_credential,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
