from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.modules.booking.cloud_client import BookingCloudClient
from app.modules.booking.cloud_processor import BookingCloudProcessor
from app.modules.booking.tasks import sync_cloud_booking_requests


class ScalarListResult:
    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class ScalarOneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class DurableStore:
    def __init__(self):
        self.receipt = None
        self.commits = 0
        self.rollbacks = 0


class FakeSession:
    def __init__(self, *, clinic_id, store):
        self.clinic_id = clinic_id
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    async def execute(
        self,
        statement,
        params=None,
    ):
        statement_text = str(statement)

        if "booking_settings.clinic_id" in statement_text:
            return ScalarListResult([self.clinic_id])

        if "pg_advisory_xact_lock" in statement_text:
            return ScalarOneResult(None)

        if "booking_cloud_requests" in statement_text:
            return ScalarOneResult(self.store.receipt)

        raise AssertionError("Unexpected SQL statement in synthetic E2E session")

    def add(self, instance):
        self.store.receipt = instance

    async def flush(self):
        return None

    async def commit(self):
        self.store.commits += 1

    async def rollback(self):
        self.store.rollbacks += 1


class FakeSessionFactory:
    def __init__(self, *, clinic_id, store):
        self.clinic_id = clinic_id
        self.store = store
        self.calls = 0

    def __call__(self):
        self.calls += 1

        return FakeSession(
            clinic_id=self.clinic_id,
            store=self.store,
        )


@pytest.mark.asyncio
async def test_cloud_sync_end_to_end_retries_result_without_duplicate_booking(
    monkeypatch,
):
    from app.modules.booking import tasks

    clinic_id = uuid4()
    professional_id = uuid4()
    appointment_id = uuid4()

    request_id = "request-e2e-1"

    cloud_request = {
        "request_id": request_id,
        "status": "delivered",
        "local_professional_id": str(professional_id),
        "professional_slug": "doctor-one",
        "professional_name": "Synthetic Doctor",
        "start_time": "2030-01-10T10:00:00+00:00",
        "end_time": "2030-01-10T10:30:00+00:00",
        "patient": {
            "first_name": "Synthetic",
            "last_name": "Patient",
            "phone": "+201000000000",
            "date_of_birth": "1990-01-01",
            "email": "synthetic@example.com",
        },
        "created_at": "2030-01-01T10:00:00+00:00",
        "delivered_at": "2030-01-01T10:00:01+00:00",
    }

    monkeypatch.setattr(
        tasks.settings,
        "BOOKING_CLOUD_BASE_URL",
        "https://booking.example.com",
    )

    credential_calls = 0
    authorization_headers = []
    posted_results = []
    result_attempts = 0

    async def credential_resolver() -> str:
        nonlocal credential_calls

        credential_calls += 1
        return "synthetic-signed-lease"

    def cloud_handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal result_attempts

        authorization_headers.append(request.headers.get("Authorization"))

        if request.method == "GET" and request.url.path == "/api/v1/sync/requests":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {"requests": [cloud_request]},
                },
            )

        if (
            request.method == "POST"
            and request.url.path == f"/api/v1/sync/requests/{request_id}/result"
        ):
            result_attempts += 1

            payload = json.loads(request.content.decode("utf-8"))

            posted_results.append(payload)

            # Simulate the classic dangerous case:
            # local appointment is already durable, but the first
            # outbound result acknowledgement fails.
            if result_attempts == 1:
                return httpx.Response(
                    503,
                    json={
                        "ok": False,
                    },
                )

            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "request_id": request_id,
                        **payload,
                    },
                },
            )

        raise AssertionError("Unexpected cloud request in synthetic E2E test")

    client = BookingCloudClient(
        base_url="https://booking.example.com",
        credential_resolver=credential_resolver,
        transport=httpx.MockTransport(cloud_handler),
        timeout_seconds=5.0,
    )

    store = DurableStore()

    sessions = FakeSessionFactory(
        clinic_id=clinic_id,
        store=store,
    )

    booking_calls = 0

    async def settings_resolver(
        db,
        wanted_clinic_id,
    ):
        assert wanted_clinic_id == clinic_id

        return SimpleNamespace(
            clinic_id=clinic_id,
            enabled=True,
        )

    async def booking_creator(
        db,
        settings,
        data,
    ):
        nonlocal booking_calls

        booking_calls += 1

        assert settings.clinic_id == clinic_id
        assert data.professional_id == professional_id
        assert data.first_name == "Synthetic"
        assert data.last_name == "Patient"

        return (
            SimpleNamespace(
                id=appointment_id,
            ),
            SimpleNamespace(),
        )

    def processor_factory(
        *,
        cloud_client,
    ):
        assert cloud_client is client

        return BookingCloudProcessor(
            cloud_client=cloud_client,
            settings_resolver=settings_resolver,
            booking_creator=booking_creator,
        )

    # First cycle:
    # local result commits, cloud result POST fails transiently.
    await sync_cloud_booking_requests(
        client_factory=lambda: client,
        session_factory=sessions,
        processor_factory=processor_factory,
    )

    assert booking_calls == 1
    assert store.receipt is not None
    assert store.receipt.status == "accepted"
    assert store.receipt.appointment_id == appointment_id
    assert store.rollbacks == 0

    # Second cycle:
    # same delivered cloud request is pulled again.
    # Durable receipt must replay the exact result without
    # creating another appointment.
    await sync_cloud_booking_requests(
        client_factory=lambda: client,
        session_factory=sessions,
        processor_factory=processor_factory,
    )

    assert booking_calls == 1

    expected_result = {
        "status": "accepted",
        "local_appointment_id": str(appointment_id),
    }

    assert posted_results == [
        expected_result,
        expected_result,
    ]

    assert result_attempts == 2

    # GET + POST on each cycle. Credential is resolved fresh
    # for every outbound HTTPS request.
    assert credential_calls == 4

    assert authorization_headers == [
        "Bearer synthetic-signed-lease",
        "Bearer synthetic-signed-lease",
        "Bearer synthetic-signed-lease",
        "Bearer synthetic-signed-lease",
    ]
