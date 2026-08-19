from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from app.modules.booking import BookingModule
from app.modules.booking.cloud_client import BookingCloudTransientError
from app.modules.booking.tasks import sync_cloud_booking_requests


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self, clinic_ids):
        self.clinic_ids = clinic_ids

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    async def execute(self, statement):
        return FakeScalarResult(
            self.clinic_ids
        )


class FakeSessionFactory:
    def __init__(self, clinic_ids):
        self.clinic_ids = clinic_ids
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return FakeSession(
            self.clinic_ids
        )


class FakeClient:
    def __init__(
        self,
        requests=None,
        failure=None,
    ):
        self.requests = list(requests or [])
        self.failure = failure
        self.pull_count = 0

    async def pull_requests(self):
        self.pull_count += 1

        if self.failure is not None:
            raise self.failure

        return list(self.requests)


class RecordingProcessor:
    def __init__(
        self,
        *,
        cloud_client,
        failure_on_request=None,
    ):
        self.cloud_client = cloud_client
        self.failure_on_request = failure_on_request
        self.calls = []

    async def process_request(
        self,
        db,
        *,
        clinic_id,
        request,
    ):
        request_id = request["request_id"]

        self.calls.append(
            (
                clinic_id,
                request_id,
            )
        )

        if request_id == self.failure_on_request:
            raise RuntimeError(
                "SYNTHETIC_PRIVATE_VALUE"
            )

        return {
            "status": "accepted",
            "local_appointment_id": str(uuid4()),
        }


def test_booking_module_registers_single_safe_sync_job():
    jobs = BookingModule().get_scheduled_jobs()

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "booking_cloud_sync"
    assert job.func is sync_cloud_booking_requests
    assert job.trigger == "interval"
    assert job.trigger_args == {
        "seconds": 30,
    }
    assert job.max_instances == 1


@pytest.mark.asyncio
async def test_sync_is_disabled_without_cloud_url(
    monkeypatch,
):
    from app.modules.booking import tasks

    monkeypatch.setattr(
        tasks.settings,
        "BOOKING_CLOUD_BASE_URL",
        "",
    )

    def should_not_run():
        raise AssertionError(
            "disabled cloud sync touched dependencies"
        )

    await sync_cloud_booking_requests(
        client_factory=should_not_run,
        session_factory=should_not_run,
    )


@pytest.mark.asyncio
async def test_sync_refuses_ambiguous_local_clinic(
    monkeypatch,
):
    from app.modules.booking import tasks

    monkeypatch.setattr(
        tasks.settings,
        "BOOKING_CLOUD_BASE_URL",
        "https://booking.example.com",
    )

    clinic_one = uuid4()
    clinic_two = uuid4()

    sessions = FakeSessionFactory(
        [
            clinic_one,
            clinic_two,
        ]
    )
    client = FakeClient(
        [
            {"request_id": "request-1"},
        ]
    )

    await sync_cloud_booking_requests(
        client_factory=lambda: client,
        session_factory=sessions,
    )

    assert sessions.calls == 1
    assert client.pull_count == 0


@pytest.mark.asyncio
async def test_sync_pulls_and_processes_each_request(
    monkeypatch,
):
    from app.modules.booking import tasks

    monkeypatch.setattr(
        tasks.settings,
        "BOOKING_CLOUD_BASE_URL",
        "https://booking.example.com",
    )

    clinic_id = uuid4()

    sessions = FakeSessionFactory(
        [clinic_id]
    )

    client = FakeClient(
        [
            {"request_id": "request-1"},
            {"request_id": "request-2"},
        ]
    )

    processor = RecordingProcessor(
        cloud_client=client,
    )

    def processor_factory(
        *,
        cloud_client,
    ):
        assert cloud_client is client
        return processor

    await sync_cloud_booking_requests(
        client_factory=lambda: client,
        session_factory=sessions,
        processor_factory=processor_factory,
    )

    assert client.pull_count == 1

    assert processor.calls == [
        (
            clinic_id,
            "request-1",
        ),
        (
            clinic_id,
            "request-2",
        ),
    ]

    # One mapping session + one isolated processing
    # session for every pulled cloud request.
    assert sessions.calls == 3


@pytest.mark.asyncio
async def test_one_request_failure_does_not_block_next_or_log_private_value(
    monkeypatch,
    caplog,
):
    from app.modules.booking import tasks

    monkeypatch.setattr(
        tasks.settings,
        "BOOKING_CLOUD_BASE_URL",
        "https://booking.example.com",
    )

    clinic_id = uuid4()

    sessions = FakeSessionFactory(
        [clinic_id]
    )

    client = FakeClient(
        [
            {"request_id": "request-1"},
            {"request_id": "request-2"},
        ]
    )

    processor = RecordingProcessor(
        cloud_client=client,
        failure_on_request="request-1",
    )

    with caplog.at_level(
        logging.ERROR,
        logger="app.modules.booking.tasks",
    ):
        await sync_cloud_booking_requests(
            client_factory=lambda: client,
            session_factory=sessions,
            processor_factory=lambda **kwargs: processor,
        )

    assert processor.calls == [
        (
            clinic_id,
            "request-1",
        ),
        (
            clinic_id,
            "request-2",
        ),
    ]

    assert "SYNTHETIC_PRIVATE_VALUE" not in caplog.text


@pytest.mark.asyncio
async def test_cloud_pull_failure_is_retryable_and_not_logged_verbatim(
    monkeypatch,
    caplog,
):
    from app.modules.booking import tasks

    monkeypatch.setattr(
        tasks.settings,
        "BOOKING_CLOUD_BASE_URL",
        "https://booking.example.com",
    )

    clinic_id = uuid4()

    sessions = FakeSessionFactory(
        [clinic_id]
    )

    client = FakeClient(
        failure=BookingCloudTransientError(
            "SYNTHETIC_REMOTE_PRIVATE_VALUE"
        )
    )

    with caplog.at_level(
        logging.WARNING,
        logger="app.modules.booking.tasks",
    ):
        await sync_cloud_booking_requests(
            client_factory=lambda: client,
            session_factory=sessions,
        )

    assert client.pull_count == 1
    assert "SYNTHETIC_REMOTE_PRIVATE_VALUE" not in caplog.text
