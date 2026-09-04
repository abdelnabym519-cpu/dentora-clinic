"""Tests for multi-tenant resource isolation.

One clinic must not be able to consume shared resources (process, DB
pool, disk, outbox ticks, copilot streams) in a way that degrades the
others. Covers the controls added in the MULTI-TENANT RESOURCE
ISOLATION phase plus the pre-existing guardrail session cap:

* per-tenant request rate + concurrency middleware (normal + adversarial)
* per-clinic copilot stream cap (incl. cross-tenant independence)
* notifications outbox per-clinic fairness
* media upload byte cap + per-clinic storage quota
* agent guardrail session-lifetime cap (regression: window vs total)
* shared-engine statement_timeout wiring
"""

from __future__ import annotations

import asyncio
import time
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import UploadFile
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.agents import AgentContext, AgentMode, Tool, ToolCategory, tool_registry
from app.core.agents.guardrails import (
    GuardrailConfig,
    GuardrailDecision,
    check,
)
from app.core.agents.guardrails import (
    reset_counters as reset_guardrail_counters,
)
from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.core.tenant_limits import (
    check_and_acquire,
    release,
    reset_state,
    resolve_tenant_key,
)
from app.database import async_session_maker
from app.main import app
from app.modules.copilot.router import (
    _active_streams,
    _stream,
    reset_stream_counters,
)
from app.modules.media.validation import read_capped_upload
from app.modules.notifications.gateway import NotificationGateway
from app.modules.notifications.models import CommunicationMessage
from app.modules.patients.models import Patient


@pytest.fixture(autouse=True)
def _clean_state():
    reset_state()
    reset_stream_counters()
    reset_guardrail_counters()
    yield
    reset_state()
    reset_stream_counters()
    reset_guardrail_counters()


def _clinic_token(clinic_id=None) -> str:
    return create_access_token(uuid4(), clinic_id=clinic_id)


# --------------------------------------------------------------------------- #
# Tenant key resolution
# --------------------------------------------------------------------------- #


class _Req:
    """Minimal stand-in shaped like what resolve_tenant_key needs."""

    def __init__(self, authorization: str = "", ip: str = "9.9.9.9"):
        self.headers = {"authorization": authorization} if authorization else {}
        self._ip = ip


def _key_for(authorization: str = "") -> str:
    # resolve_tenant_key only touches .headers + get_remote_address.
    from unittest.mock import patch

    req = _Req(authorization)
    with patch("app.core.tenant_limits.get_remote_address", return_value=req._ip):
        return resolve_tenant_key(req)  # type: ignore[arg-type]


def test_key_is_clinic_scoped_for_clinic_jwt():
    cid = uuid4()
    assert _key_for(f"Bearer {_clinic_token(cid)}") == f"clinic:{cid}"


def test_key_falls_back_to_user_without_clinic_claim():
    token = _clinic_token(None)
    key = _key_for(f"Bearer {token}")
    assert key.startswith("user:")


def test_key_falls_back_to_ip_for_bad_token():
    assert _key_for("Bearer garbage.token.here") == "ip:9.9.9.9"


def test_key_falls_back_to_ip_without_auth():
    assert _key_for() == "ip:9.9.9.9"


# --------------------------------------------------------------------------- #
# Rate + concurrency core
# --------------------------------------------------------------------------- #


def test_rate_blocks_past_per_minute_cap(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 3)
    monkeypatch.setattr(settings, "TENANT_MAX_CONCURRENT_REQUESTS", 50)
    key = "clinic:rate-a"
    for _ in range(3):
        v = check_and_acquire(key)
        assert v.allowed
        release(key)
    # Fourth acquisition without release still counts in the window.
    check_and_acquire(key)
    check_and_acquire(key)
    check_and_acquire(key)
    verdict = check_and_acquire(key)
    assert not verdict.allowed
    assert verdict.reason == "rate"
    assert verdict.retry_after >= 1


def test_buckets_are_independent_per_tenant(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 2)
    monkeypatch.setattr(settings, "TENANT_MAX_CONCURRENT_REQUESTS", 50)
    for _ in range(2):
        check_and_acquire("clinic:noisy")
    assert not check_and_acquire("clinic:noisy").allowed
    # The quiet tenant is unaffected by the noisy neighbour.
    assert check_and_acquire("clinic:quiet").allowed


def test_concurrency_cap_and_release(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_MAX_CONCURRENT_REQUESTS", 2)
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 1000)
    assert check_and_acquire("clinic:busy").allowed
    assert check_and_acquire("clinic:busy").allowed
    assert not check_and_acquire("clinic:busy").allowed
    release("clinic:busy")
    assert check_and_acquire("clinic:busy").allowed


async def test_concurrent_burst_shares_one_gauge(monkeypatch):
    """True overlap: 5 contenders race for 3 slots; all extra are denied."""
    monkeypatch.setattr(settings, "TENANT_MAX_CONCURRENT_REQUESTS", 3)
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 1000)
    key = "clinic:burst"
    holders = [check_and_acquire(key) for _ in range(3)]
    assert all(h.allowed for h in holders)

    entered = asyncio.Event()

    async def contender():
        await asyncio.sleep(0)  # force a real overlap window
        entered.set()
        return check_and_acquire(key)

    results = await asyncio.gather(*[contender() for _ in range(5)])
    assert entered.is_set()
    assert all(not r.allowed and r.reason == "concurrency" for r in results)

    for _ in range(3):
        release(key)
    assert check_and_acquire(key).allowed


def test_limits_disabled_allows_everything(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_LIMITS_ENABLED", False)
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "TENANT_MAX_CONCURRENT_REQUESTS", 1)
    assert check_and_acquire("clinic:any").allowed
    assert check_and_acquire("clinic:any").allowed


# --------------------------------------------------------------------------- #
# Middleware integration through the real app
# --------------------------------------------------------------------------- #


async def _get_api_root(token: str | None):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get("/api/v1", headers=headers)


async def test_middleware_returns_429_for_abusive_tenant(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 4)
    noisy = _clinic_token(uuid4())
    for _ in range(4):
        resp = await _get_api_root(noisy)
        assert resp.status_code == 200
    abused = await _get_api_root(noisy)
    assert abused.status_code == 429
    body = abused.json()
    assert body["data"] is None
    assert "Retry-After" in abused.headers


async def test_middleware_isolates_quiet_tenant_from_noisy_one(monkeypatch):
    """Cross-tenant abuse scenario: A floods, B keeps working."""
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 3)
    noisy = _clinic_token(uuid4())
    quiet = _clinic_token(uuid4())
    for _ in range(3):
        assert (await _get_api_root(noisy)).status_code == 200
    assert (await _get_api_root(noisy)).status_code == 429
    # The quiet tenant is unaffected end to end.
    assert (await _get_api_root(quiet)).status_code == 200


async def test_health_stays_exempt_under_load(monkeypatch):
    monkeypatch.setattr(settings, "TENANT_MAX_REQUESTS_PER_MINUTE", 1)
    token = _clinic_token(uuid4())
    assert (await _get_api_root(token)).status_code == 200
    assert (await _get_api_root(token)).status_code == 429
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(3):
            resp = await ac.get("/health", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Shared-engine statement timeout
# --------------------------------------------------------------------------- #


async def test_engine_applies_configured_statement_timeout():
    async with async_session_maker() as session:
        value = await session.scalar(text("SELECT current_setting('statement_timeout')"))
    assert value == "30s"


# --------------------------------------------------------------------------- #
# Guardrail session-lifetime cap (window vs total regression)
# --------------------------------------------------------------------------- #


class _Args(BaseModel):
    x: int = 0


async def _noop(ctx, params):
    return None


def _make_ctx(session_id=None) -> AgentContext:
    return AgentContext(
        agent_id=uuid4(),
        session_id=session_id or uuid4(),
        clinic_id=uuid4(),
        mode=AgentMode.AUTONOMOUS,
        permissions=["*"],
        tools=tool_registry,
        db=None,
    )


def _read_tool() -> Tool:
    return Tool(
        name="m.r",
        description="x",
        parameters=_Args,
        handler=_noop,
        permissions=[],
        category=ToolCategory.READ,
    )


def test_session_cap_counts_lifetime_actions_not_window(monkeypatch):
    """The 60s window expiring must NOT reset the per-session total."""
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    cfg = GuardrailConfig(max_actions_per_minute=1000, max_actions_per_session=2)
    ctx = _make_ctx()
    assert check(ctx, _read_tool(), "m.r", cfg) is GuardrailDecision.ALLOW
    assert check(ctx, _read_tool(), "m.r", cfg) is GuardrailDecision.ALLOW
    now[0] = 61.0  # slide past the rate window
    assert check(ctx, _read_tool(), "m.r", cfg) is GuardrailDecision.BLOCK


def test_per_minute_cap_still_binds_first():
    cfg = GuardrailConfig(max_actions_per_minute=2, max_actions_per_session=100)
    ctx = _make_ctx()
    assert check(ctx, _read_tool(), "m.r", cfg) is GuardrailDecision.ALLOW
    assert check(ctx, _read_tool(), "m.r", cfg) is GuardrailDecision.ALLOW
    assert check(ctx, _read_tool(), "m.r", cfg) is GuardrailDecision.BLOCK


# --------------------------------------------------------------------------- #
# Media upload byte cap
# --------------------------------------------------------------------------- #


async def test_read_capped_upload_rejects_oversized_body(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 1024)
    too_big = UploadFile(file=BytesIO(b"x" * 2049), filename="big.pdf")
    with pytest.raises(Exception) as exc_info:
        await read_capped_upload(too_big)
    assert getattr(exc_info.value, "status_code", None) == 413

    ok_file = UploadFile(file=BytesIO(b"x" * 512), filename="ok.pdf")
    assert await read_capped_upload(ok_file) == b"x" * 512


async def _clinic_with_patient(
    db_session: AsyncSession, client: AsyncClient, email: str
) -> tuple[str, str]:
    user = User(
        email=email,
        password_hash=hash_password("TestPass1234"),
        first_name="Quota",
        last_name="Test",
    )
    db_session.add(user)
    await db_session.flush()
    clinic = Clinic(
        id=uuid4(),
        name=f"Quota clinic {email}",
        tax_id="B12345678",
        address={},
        settings={},
    )
    db_session.add(clinic)
    await db_session.flush()
    db_session.add(ClinicMembership(id=uuid4(), user_id=user.id, clinic_id=clinic.id, role="admin"))
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic.id,
        first_name="Quota",
        last_name="Patient",
    )
    db_session.add(patient)
    await db_session.commit()
    token = create_access_token(user.id, clinic_id=clinic.id)
    return f"Bearer {token}", str(patient.id)


def _pdf_bytes(size: int) -> bytes:
    body = b"%PDF-1.4\n" + b"x" * size + b"\n%%EOF"
    return body


async def test_upload_endpoint_enforces_byte_cap(
    db_session: AsyncSession, client, monkeypatch
) -> None:
    """Adversarial: Content-Length says nothing; actual bytes must be capped."""
    monkeypatch.setattr(settings, "STORAGE_MAX_FILE_SIZE", 1024)
    auth, patient_id = await _clinic_with_patient(db_session, client, "cap-a@t.test")

    big = await client.post(
        f"/api/v1/media/patients/{patient_id}/documents",
        headers={"Authorization": auth},
        files={"file": ("big.pdf", BytesIO(_pdf_bytes(2048)), "application/pdf")},
        data={"document_type": "other", "title": "big"},
    )
    assert big.status_code == 413

    small = await client.post(
        f"/api/v1/media/patients/{patient_id}/documents",
        headers={"Authorization": auth},
        files={"file": ("small.pdf", BytesIO(_pdf_bytes(100)), "application/pdf")},
        data={"document_type": "other", "title": "small"},
    )
    assert small.status_code == 201


async def test_storage_quota_is_per_clinic(db_session: AsyncSession, client, monkeypatch) -> None:
    """Clinic A hitting quota must not block clinic B (isolation)."""
    auth_a, patient_a = await _clinic_with_patient(db_session, client, "quota-a@t.test")
    auth_b, patient_b = await _clinic_with_patient(db_session, client, "quota-b@t.test")

    one = _pdf_bytes(200)
    monkeypatch.setattr(settings, "STORAGE_QUOTA_BYTES_PER_CLINIC", len(one) + 10)

    async def upload(auth, patient_id, payload: bytes, title: str):
        return await client.post(
            f"/api/v1/media/patients/{patient_id}/documents",
            headers={"Authorization": auth},
            files={"file": ("f.pdf", BytesIO(payload), "application/pdf")},
            data={"document_type": "other", "title": title},
        )

    assert (await upload(auth_a, patient_a, one, "a1")).status_code == 201
    over = await upload(auth_a, patient_a, one, "a2")
    assert over.status_code == 413
    assert "quota" in over.json()["message"].lower()
    # Clinic B has its own ledger: unaffected by A's usage.
    assert (await upload(auth_b, patient_b, one, "b1")).status_code == 201


async def test_quota_accounting_matches_stored_bytes(
    db_session: AsyncSession, client, monkeypatch
) -> None:
    auth, patient_id = await _clinic_with_patient(db_session, client, "quota-c@t.test")
    payload = _pdf_bytes(300)
    monkeypatch.setattr(settings, "STORAGE_QUOTA_BYTES_PER_CLINIC", len(payload) + 5)
    resp = await client.post(
        f"/api/v1/media/patients/{patient_id}/documents",
        headers={"Authorization": auth},
        files={"file": ("f.pdf", BytesIO(payload), "application/pdf")},
        data={"document_type": "other", "title": "c1"},
    )
    assert resp.status_code == 201
    clinic_id = await db_session.scalar(
        select(Clinic.id).where(Clinic.name == "Quota clinic quota-c@t.test")
    )
    used = await db_session.scalar(
        select(
            func.coalesce(
                func.sum(
                    __import__("app.modules.media.models", fromlist=["Document"]).Document.file_size
                ),
                0,
            )
        ).where(
            __import__("app.modules.media.models", fromlist=["Document"]).Document.clinic_id
            == clinic_id
        )
    )
    assert used == len(payload)


# --------------------------------------------------------------------------- #
# Copilot stream cap
# --------------------------------------------------------------------------- #


def test_copilot_stream_cap_blocks_saturated_clinic(monkeypatch):
    from uuid import UUID as _UUID

    monkeypatch.setattr(settings, "COPILOT_MAX_CONCURRENT_STREAMS_PER_CLINIC", 2)
    cid: _UUID = uuid4()
    other: _UUID = uuid4()

    async def factory(db):
        return
        yield  # make it an async generator

    from app.modules.copilot.router import _try_acquire_stream

    assert _try_acquire_stream(cid)
    assert _try_acquire_stream(cid)
    saturated = _stream(factory, clinic_id=cid)
    assert saturated.status_code == 429
    # Another clinic is independent.
    assert _stream(factory, clinic_id=other).status_code != 429
    assert _active_streams.get(other, 0) == 1


async def test_copilot_stream_releases_slot_on_completion(monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_MAX_CONCURRENT_STREAMS_PER_CLINIC", 1)
    cid = uuid4()

    async def factory(db):
        return
        yield

    resp = _stream(factory, clinic_id=cid)
    assert resp.status_code == 200
    assert _active_streams.get(cid, 0) == 1
    async for _ in resp.body_iterator:
        pass
    assert _active_streams.get(cid, 0) == 0
    # Slot reusable after the stream ends.
    assert _stream(factory, clinic_id=cid).status_code == 200


# --------------------------------------------------------------------------- #
# Outbox fairness
# --------------------------------------------------------------------------- #


async def _seed_outbox(db_session: AsyncSession, clinic_id, count: int) -> None:
    for i in range(count):
        db_session.add(
            CommunicationMessage(
                clinic_id=clinic_id,
                channel="email",
                to_address=f"u{i}@example.test",
                template_key="fairness-probe",
                message_kind="session",
                body_text="reminder",
                status="queued",
            )
        )
    await db_session.commit()


async def test_outbox_tick_caps_noisy_clinic(
    db_session: AsyncSession, test_clinic: Clinic, monkeypatch
) -> None:
    """Adversarial: clinic A floods the outbox; clinic B must still send."""
    from app.core.auth.models import Clinic as _Clinic

    monkeypatch.setattr(settings, "NOTIFICATIONS_MAX_PER_CLINIC_PER_TICK", 10)
    clinic_b = _Clinic(id=uuid4(), name="Fair B", tax_id="B00000002", address={}, settings={})
    db_session.add(clinic_b)
    await db_session.commit()

    await _seed_outbox(db_session, test_clinic.id, 25)
    await _seed_outbox(db_session, clinic_b.id, 3)

    attempted = await NotificationGateway.dispatch_outbox(db_session, limit=50)
    assert attempted == 13  # 10 for A + 3 for B, not 28 FIFO for A

    remaining_a = await db_session.scalar(
        select(func.count())
        .select_from(CommunicationMessage)
        .where(
            CommunicationMessage.clinic_id == test_clinic.id,
            CommunicationMessage.status == "queued",
        )
    )
    remaining_b = await db_session.scalar(
        select(func.count())
        .select_from(CommunicationMessage)
        .where(
            CommunicationMessage.clinic_id == clinic_b.id,
            CommunicationMessage.status == "queued",
        )
    )
    assert remaining_a == 15
    assert remaining_b == 0
