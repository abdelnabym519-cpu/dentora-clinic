"""Evolution provider public webhook integration/security tests."""

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email.encryption import encrypt_password
from app.modules.notifications.models import CommunicationMessage
from app.modules.whatsapp_evolution.models import (
    WhatsappEvolutionSettings,
    WhatsappEvolutionWebhookReceipt,
)

_TOKEN = "test-webhook-token-1234567890"


async def _settings(db, clinic_id, *, instance="clinic-a"):
    row = WhatsappEvolutionSettings(
        clinic_id=clinic_id,
        base_url="http://evolution.test:8080",
        instance_name=instance,
        api_key_encrypted=encrypt_password("api-key-123"),
        webhook_token_encrypted=encrypt_password(_TOKEN),
        is_active=True,
        is_verified=True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _raw(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


@pytest.mark.asyncio
async def test_delivery_webhook_updates_message_once(
    client: AsyncClient, db_session: AsyncSession, test_patient
):
    settings = await _settings(db_session, test_patient.clinic_id)
    sent = CommunicationMessage(
        clinic_id=test_patient.clinic_id,
        channel="whatsapp",
        to_address=test_patient.phone,
        patient_id=test_patient.id,
        template_key="prescription",
        message_kind="text",
        status="sent",
        provider="whatsapp_evolution",
        provider_message_id="EVO-OUT-1",
    )
    db_session.add(sent)
    await db_session.commit()

    payload = {
        "event": "MESSAGES_UPDATE",
        "instance": "clinic-a",
        "data": [{"key": {"id": "EVO-OUT-1"}, "update": {"status": 3}}],
    }
    raw = _raw(payload)
    headers = {
        "X-Dentora-Webhook-Token": _TOKEN,
        "Content-Type": "application/json",
    }
    url = f"/api/v1/whatsapp_evolution/webhook/{settings.id}"

    first = await client.post(url, content=raw, headers=headers)
    assert first.status_code == 200
    await db_session.refresh(sent)
    assert sent.status == "delivered"
    assert sent.delivered_at is not None

    second = await client.post(url, content=raw, headers=headers)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    receipt_count = (
        await db_session.execute(
            select(func.count()).select_from(WhatsappEvolutionWebhookReceipt).where(
                WhatsappEvolutionWebhookReceipt.clinic_id == test_patient.clinic_id
            )
        )
    ).scalar_one()
    assert receipt_count == 1


@pytest.mark.asyncio
async def test_forged_webhook_token_is_rejected(
    client: AsyncClient, db_session: AsyncSession, test_clinic
):
    settings = await _settings(db_session, test_clinic.id)
    payload = {"event": "MESSAGES_UPDATE", "instance": "clinic-a", "data": []}
    response = await client.post(
        f"/api/v1/whatsapp_evolution/webhook/{settings.id}",
        content=_raw(payload),
        headers={"X-Dentora-Webhook-Token": "wrong-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_instance_mismatch_is_rejected(
    client: AsyncClient, db_session: AsyncSession, test_clinic
):
    settings = await _settings(db_session, test_clinic.id, instance="clinic-a")
    payload = {"event": "CONNECTION_UPDATE", "instance": "clinic-b", "data": {"state": "open"}}
    response = await client.post(
        f"/api/v1/whatsapp_evolution/webhook/{settings.id}",
        content=_raw(payload),
        headers={"X-Dentora-Webhook-Token": _TOKEN},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_unknown_webhook_binding_is_accepted_and_ignored(client: AsyncClient):
    response = await client.post(
        f"/api/v1/whatsapp_evolution/webhook/{uuid4()}",
        content=_raw({"event": "MESSAGES_UPDATE", "data": []}),
    )
    assert response.status_code == 200
