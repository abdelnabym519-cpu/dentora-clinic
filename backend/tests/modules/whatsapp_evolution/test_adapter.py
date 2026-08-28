"""EvolutionApiAdapter unit tests (provider HTTP mocked)."""

import pytest

from app.core.email.encryption import encrypt_password
from app.modules.notifications.channels import Channel, OutboundMessage, SendStatus
from app.modules.whatsapp_evolution import client
from app.modules.whatsapp_evolution.adapter import EvolutionApiAdapter
from app.modules.whatsapp_evolution.models import WhatsappEvolutionSettings


async def _settings(db, clinic_id, *, verified=True):
    settings = WhatsappEvolutionSettings(
        clinic_id=clinic_id,
        base_url="http://evolution.test:8080",
        instance_name="clinic-a",
        api_key_encrypted=encrypt_password("api-key-123"),
        webhook_token_encrypted=encrypt_password("webhook-token-1234567890"),
        is_active=True,
        is_verified=verified,
    )
    db.add(settings)
    await db.commit()
    return settings


def _message(clinic_id, body="Prescription ready"):
    return OutboundMessage(
        channel=Channel.WHATSAPP,
        to_address="+34 600 111 222",
        clinic_id=clinic_id,
        template_key="prescription",
        message_kind="text",
        body_text=body,
    )


@pytest.mark.asyncio
async def test_send_text_returns_provider_message_id(db_session, test_clinic, monkeypatch):
    await _settings(db_session, test_clinic.id)
    captured = {}

    async def fake_send(base_url, api_key, instance, number, text):
        captured.update(
            base_url=base_url,
            api_key=api_key,
            instance=instance,
            number=number,
            text=text,
        )
        return {"key": {"id": "EVOMSG1"}, "status": "PENDING"}

    monkeypatch.setattr(client, "send_text", fake_send)
    result = await EvolutionApiAdapter().send(db_session, _message(test_clinic.id))

    assert result.status == SendStatus.SENT
    assert result.provider_message_id == "EVOMSG1"
    assert result.provider == "whatsapp_evolution"
    assert captured["instance"] == "clinic-a"
    assert captured["number"] == "+34 600 111 222"
    assert captured["text"] == "Prescription ready"


@pytest.mark.asyncio
async def test_supports_requires_active_verified_settings(db_session, test_clinic):
    adapter = EvolutionApiAdapter()
    assert await adapter.supports(db_session, test_clinic.id) is False
    settings = await _settings(db_session, test_clinic.id, verified=False)
    assert await adapter.supports(db_session, test_clinic.id) is False
    settings.is_verified = True
    await db_session.commit()
    assert await adapter.supports(db_session, test_clinic.id) is True


@pytest.mark.asyncio
async def test_permanent_provider_failure_is_not_retryable(db_session, test_clinic, monkeypatch):
    await _settings(db_session, test_clinic.id)

    async def fail(*args):
        raise client.EvolutionApiError("request_failed", status_code=400, retryable=False)

    monkeypatch.setattr(client, "send_text", fail)
    result = await EvolutionApiAdapter().send(db_session, _message(test_clinic.id))
    assert result.status == SendStatus.FAILED
    assert result.retryable is False
    assert "HTTP 400" in (result.error_message or "")


@pytest.mark.asyncio
async def test_transient_provider_failure_is_retryable(db_session, test_clinic, monkeypatch):
    await _settings(db_session, test_clinic.id)

    async def fail(*args):
        raise client.EvolutionApiError("timeout", retryable=True)

    monkeypatch.setattr(client, "send_text", fail)
    result = await EvolutionApiAdapter().send(db_session, _message(test_clinic.id))
    assert result.status == SendStatus.FAILED
    assert result.retryable is True
