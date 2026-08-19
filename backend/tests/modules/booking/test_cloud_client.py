from __future__ import annotations

import json

import httpx
import pytest


@pytest.fixture
def signed_lease() -> str:
    return "signed.test.lease"


@pytest.fixture
def credential_resolver(signed_lease: str):
    calls = {"count": 0}

    async def resolve() -> str:
        calls["count"] += 1
        return signed_lease

    resolve.calls = calls
    return resolve


@pytest.mark.asyncio
async def test_pull_requests_uses_bearer_auth_and_exact_sync_path(
    signed_lease: str,
    credential_resolver,
) -> None:
    from app.modules.booking.cloud_client import BookingCloudClient

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")

        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "requests": [
                        {
                            "request_id": "request-1",
                            "status": "delivered",
                        }
                    ],
                    "count": 1,
                },
            },
        )

    client = BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    requests = await client.pull_requests()

    assert captured == {
        "method": "GET",
        "path": "/api/v1/sync/requests",
        "authorization": f"Bearer {signed_lease}",
    }

    assert requests == [
        {
            "request_id": "request-1",
            "status": "delivered",
        }
    ]

    assert credential_resolver.calls["count"] == 1


@pytest.mark.asyncio
async def test_resolve_accepted_request_posts_exact_contract(
    signed_lease: str,
    credential_resolver,
) -> None:
    from app.modules.booking.cloud_client import BookingCloudClient

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)

        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "request_id": "request-123",
                    "status": "accepted",
                    "local_appointment_id": "appointment-456",
                },
            },
        )

    client = BookingCloudClient(
        base_url="https://book.dentalpin.app/",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    await client.resolve_request(
        "request-123",
        {
            "status": "accepted",
            "local_appointment_id": "appointment-456",
        },
    )

    assert captured == {
        "method": "POST",
        "path": "/api/v1/sync/requests/request-123/result",
        "authorization": f"Bearer {signed_lease}",
        "body": {
            "status": "accepted",
            "local_appointment_id": "appointment-456",
        },
    }


@pytest.mark.asyncio
async def test_resolve_rejected_request_posts_exact_contract(
    credential_resolver,
) -> None:
    from app.modules.booking.cloud_client import BookingCloudClient

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)

        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "request_id": "request-789",
                    "status": "rejected",
                    "rejection_code": "slot_unavailable",
                },
            },
        )

    client = BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    await client.resolve_request(
        "request-789",
        {
            "status": "rejected",
            "rejection_code": "slot_unavailable",
        },
    )

    assert captured["body"] == {
        "status": "rejected",
        "rejection_code": "slot_unavailable",
    }


@pytest.mark.asyncio
async def test_client_resolves_fresh_credential_for_each_request(
    credential_resolver,
) -> None:
    from app.modules.booking.cloud_client import BookingCloudClient

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "requests": [],
                        "count": 0,
                    },
                },
            )

        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "request_id": "request-1",
                    "status": "rejected",
                    "rejection_code": "slot_unavailable",
                },
            },
        )

    client = BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    await client.pull_requests()

    await client.resolve_request(
        "request-1",
        {
            "status": "rejected",
            "rejection_code": "slot_unavailable",
        },
    )

    assert credential_resolver.calls["count"] == 2



@pytest.mark.asyncio
async def test_cloud_client_classifies_transport_failure_as_transient(
    credential_resolver,
) -> None:
    from app.modules.booking import cloud_client

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "synthetic network unavailable",
            request=request,
        )

    client = cloud_client.BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(cloud_client.BookingCloudTransientError):
        await client.pull_requests()


@pytest.mark.asyncio
async def test_cloud_client_classifies_5xx_as_transient(
    credential_resolver,
) -> None:
    from app.modules.booking import cloud_client

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "ok": False,
                "error": {
                    "code": "service_unavailable",
                },
            },
        )

    client = cloud_client.BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(cloud_client.BookingCloudTransientError):
        await client.pull_requests()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_cloud_client_classifies_auth_failures(
    credential_resolver,
    status_code: int,
) -> None:
    from app.modules.booking import cloud_client

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "ok": False,
                "error": {
                    "code": "synthetic_auth_failure",
                },
            },
        )

    client = cloud_client.BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(cloud_client.BookingCloudAuthError):
        await client.pull_requests()


@pytest.mark.asyncio
async def test_cloud_client_rejects_invalid_json_as_protocol_error(
    credential_resolver,
) -> None:
    from app.modules.booking import cloud_client

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not-json",
            headers={
                "content-type": "application/json",
            },
        )

    client = cloud_client.BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        cloud_client.BookingCloudProtocolError,
        match="invalid JSON",
    ):
        await client.pull_requests()


@pytest.mark.asyncio
async def test_cloud_client_rejects_unsuccessful_2xx_contract(
    credential_resolver,
) -> None:
    from app.modules.booking import cloud_client

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": False,
                "error": {
                    "code": "synthetic_protocol_failure",
                },
            },
        )

    client = cloud_client.BookingCloudClient(
        base_url="https://book.dentalpin.app",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        cloud_client.BookingCloudProtocolError,
        match="unsuccessful response",
    ):
        await client.pull_requests()


def test_cloud_client_requires_https_base_url(
    credential_resolver,
) -> None:
    from app.modules.booking.cloud_client import BookingCloudClient

    with pytest.raises(
        ValueError,
        match="HTTPS",
    ):
        BookingCloudClient(
            base_url="http://book.dentalpin.app",
            credential_resolver=credential_resolver,
        )
