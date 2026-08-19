from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.modules.booking.cloud_client import BookingCloudTransientError
from app.modules.booking.cloud_processor import BookingCloudProcessor
from app.modules.booking.models import BookingCloudRequest
from app.modules.booking.service import BookingUnavailableError


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self, receipt=None):
        self.receipt = receipt
        self.lock_seen = False
        self.receipt_read_after_lock = False
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, statement, params=None):
        statement_text = str(statement)

        if "pg_advisory_xact_lock" in statement_text:
            self.lock_seen = True
            return FakeScalarResult(None)

        self.receipt_read_after_lock = self.lock_seen
        return FakeScalarResult(self.receipt)

    def add(self, instance):
        self.receipt = instance

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


class FakeCloudClient:
    def __init__(self, failure=None):
        self.failure = failure
        self.resolved = []

    async def resolve_request(self, request_id, result):
        self.resolved.append((request_id, result))

        if self.failure is not None:
            raise self.failure

        return {
            "request_id": request_id,
            **result,
        }


def cloud_request(
    *,
    request_id="request-1",
    professional_id=None,
):
    professional_id = professional_id or uuid4()

    return {
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


@pytest.mark.asyncio
async def test_processor_creates_authoritative_local_booking_once():
    clinic_id = uuid4()
    appointment_id = uuid4()
    session = FakeSession()
    cloud = FakeCloudClient()

    settings = SimpleNamespace(
        clinic_id=clinic_id,
        enabled=True,
    )

    calls = {"booking": 0}

    async def settings_resolver(db, wanted_clinic_id):
        assert wanted_clinic_id == clinic_id
        return settings

    async def booking_creator(db, wanted_settings, data):
        calls["booking"] += 1

        assert wanted_settings is settings
        assert isinstance(data.professional_id, UUID)
        assert data.first_name == "Synthetic"
        assert data.last_name == "Patient"

        return (
            SimpleNamespace(id=appointment_id),
            SimpleNamespace(),
        )

    processor = BookingCloudProcessor(
        cloud_client=cloud,
        settings_resolver=settings_resolver,
        booking_creator=booking_creator,
    )

    result = await processor.process_request(
        session,
        clinic_id=clinic_id,
        request=cloud_request(),
    )

    assert result == {
        "status": "accepted",
        "local_appointment_id": str(appointment_id),
    }

    assert calls["booking"] == 1
    assert session.lock_seen is True
    assert session.receipt_read_after_lock is True
    assert session.commit_count == 1
    assert session.rollback_count == 0

    assert session.receipt.status == "accepted"
    assert session.receipt.appointment_id == appointment_id
    assert session.receipt.rejection_code is None

    assert cloud.resolved == [
        (
            "request-1",
            {
                "status": "accepted",
                "local_appointment_id": str(appointment_id),
            },
        )
    ]


@pytest.mark.asyncio
async def test_terminal_receipt_replays_without_duplicate_appointment():
    clinic_id = uuid4()
    appointment_id = uuid4()

    receipt = BookingCloudRequest(
        clinic_id=clinic_id,
        request_id="request-1",
        status="accepted",
        appointment_id=appointment_id,
    )

    session = FakeSession(receipt=receipt)
    cloud = FakeCloudClient()

    async def should_not_resolve_settings(*args, **kwargs):
        raise AssertionError("settings must not be resolved for terminal receipt")

    async def should_not_create_booking(*args, **kwargs):
        raise AssertionError("duplicate appointment creation attempted")

    processor = BookingCloudProcessor(
        cloud_client=cloud,
        settings_resolver=should_not_resolve_settings,
        booking_creator=should_not_create_booking,
    )

    result = await processor.process_request(
        session,
        clinic_id=clinic_id,
        request=cloud_request(),
    )

    assert result == {
        "status": "accepted",
        "local_appointment_id": str(appointment_id),
    }

    assert session.commit_count == 1
    assert session.rollback_count == 0
    assert cloud.resolved[0][1] == result


@pytest.mark.asyncio
async def test_booking_unavailable_becomes_stable_rejection():
    clinic_id = uuid4()
    session = FakeSession()
    cloud = FakeCloudClient()

    async def settings_resolver(db, wanted_clinic_id):
        return SimpleNamespace(
            clinic_id=wanted_clinic_id,
            enabled=True,
        )

    async def booking_creator(db, settings, data):
        raise BookingUnavailableError("Selected slot is no longer available")

    processor = BookingCloudProcessor(
        cloud_client=cloud,
        settings_resolver=settings_resolver,
        booking_creator=booking_creator,
    )

    result = await processor.process_request(
        session,
        clinic_id=clinic_id,
        request=cloud_request(),
    )

    assert result == {
        "status": "rejected",
        "rejection_code": "slot_unavailable",
    }

    assert session.receipt.status == "rejected"
    assert session.receipt.appointment_id is None
    assert session.receipt.rejection_code == "slot_unavailable"
    assert session.commit_count == 1
    assert session.rollback_count == 0
    assert cloud.resolved == [("request-1", result)]


@pytest.mark.asyncio
async def test_invalid_patient_payload_is_rejected_without_booking():
    clinic_id = uuid4()
    session = FakeSession()
    cloud = FakeCloudClient()

    request = cloud_request()
    request["patient"] = {
        "first_name": "Synthetic",
    }

    async def should_not_resolve_settings(*args, **kwargs):
        raise AssertionError("invalid payload must not reach settings")

    async def should_not_create_booking(*args, **kwargs):
        raise AssertionError("invalid payload must not create appointment")

    processor = BookingCloudProcessor(
        cloud_client=cloud,
        settings_resolver=should_not_resolve_settings,
        booking_creator=should_not_create_booking,
    )

    result = await processor.process_request(
        session,
        clinic_id=clinic_id,
        request=request,
    )

    assert result == {
        "status": "rejected",
        "rejection_code": "invalid_request",
    }

    assert session.commit_count == 1
    assert session.rollback_count == 0
    assert cloud.resolved == [("request-1", result)]


@pytest.mark.asyncio
async def test_unexpected_local_failure_rolls_back_and_does_not_reject_cloud():
    clinic_id = uuid4()
    session = FakeSession()
    cloud = FakeCloudClient()

    async def settings_resolver(db, wanted_clinic_id):
        return SimpleNamespace(
            clinic_id=wanted_clinic_id,
            enabled=True,
        )

    async def booking_creator(db, settings, data):
        raise RuntimeError("synthetic database failure")

    processor = BookingCloudProcessor(
        cloud_client=cloud,
        settings_resolver=settings_resolver,
        booking_creator=booking_creator,
    )

    with pytest.raises(RuntimeError, match="synthetic database failure"):
        await processor.process_request(
            session,
            clinic_id=clinic_id,
            request=cloud_request(),
        )

    assert session.commit_count == 0
    assert session.rollback_count == 1
    assert cloud.resolved == []


@pytest.mark.asyncio
async def test_cloud_failure_happens_after_local_result_is_committed():
    clinic_id = uuid4()
    appointment_id = uuid4()
    session = FakeSession()

    cloud = FakeCloudClient(failure=BookingCloudTransientError("synthetic cloud unavailable"))

    async def settings_resolver(db, wanted_clinic_id):
        return SimpleNamespace(
            clinic_id=wanted_clinic_id,
            enabled=True,
        )

    async def booking_creator(db, settings, data):
        return (
            SimpleNamespace(id=appointment_id),
            SimpleNamespace(),
        )

    processor = BookingCloudProcessor(
        cloud_client=cloud,
        settings_resolver=settings_resolver,
        booking_creator=booking_creator,
    )

    with pytest.raises(
        BookingCloudTransientError,
        match="synthetic cloud unavailable",
    ):
        await processor.process_request(
            session,
            clinic_id=clinic_id,
            request=cloud_request(),
        )

    assert session.commit_count == 1
    assert session.rollback_count == 0

    assert session.receipt.status == "accepted"
    assert session.receipt.appointment_id == appointment_id

    assert cloud.resolved == [
        (
            "request-1",
            {
                "status": "accepted",
                "local_appointment_id": str(appointment_id),
            },
        )
    ]
