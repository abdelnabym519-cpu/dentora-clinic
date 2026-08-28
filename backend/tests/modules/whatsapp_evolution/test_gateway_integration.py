"""Notifications/Evolution seam tests: tenant routing, consent, retry classification."""

from types import SimpleNamespace

import pytest

from app.core.email.encryption import encrypt_password
from app.modules.notifications.channels import Channel
from app.modules.notifications.gateway import NotificationGateway
from app.modules.notifications.models import ClinicChannelSettings, CommunicationMessage
from app.modules.whatsapp_evolution.models import WhatsappEvolutionSettings
from app.modules.whatsapp_kapso.models import WhatsappKapsoSettings


async def _configured_evolution(db, clinic_id):
    db.add(
        WhatsappEvolutionSettings(
            clinic_id=clinic_id,
            base_url="http://evolution.test:8080",
            instance_name="clinic-a",
            api_key_encrypted=encrypt_password("api-key-123"),
            webhook_token_encrypted=encrypt_password("webhook-token-1234567890"),
            is_active=True,
            is_verified=True,
        )
    )
    db.add(
        ClinicChannelSettings(
            clinic_id=clinic_id,
            channel="whatsapp",
            adapter_name="whatsapp_evolution",
            is_enabled=True,
            is_verified=True,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_clinic_selected_evolution_allows_opted_in_proactive_text(db_session, test_patient):
    await _configured_evolution(db_session, test_patient.clinic_id)
    prefs = SimpleNamespace(
        whatsapp_enabled=True,
        email_enabled=True,
        last_inbound_at=None,
    )

    adapter = await NotificationGateway._adapter_for_channel(
        db_session, test_patient.clinic_id, Channel.WHATSAPP
    )
    assert adapter is not None
    assert adapter.adapter_name == "whatsapp_evolution"

    resolved = await NotificationGateway._resolve_channel(
        db_session,
        test_patient.clinic_id,
        "prescription",
        test_patient,
        prefs,
        "es",
        ["whatsapp"],
        None,
        "text",
    )
    assert resolved == (Channel.WHATSAPP, test_patient.phone, "text", None)


@pytest.mark.asyncio
async def test_proactive_text_still_requires_whatsapp_opt_in(db_session, test_patient):
    await _configured_evolution(db_session, test_patient.clinic_id)
    prefs = SimpleNamespace(
        whatsapp_enabled=False,
        email_enabled=True,
        last_inbound_at=None,
    )
    resolved = await NotificationGateway._resolve_channel(
        db_session,
        test_patient.clinic_id,
        "prescription",
        test_patient,
        prefs,
        "es",
        ["whatsapp"],
        None,
        "text",
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_disabled_clinic_selector_fails_closed(db_session, test_patient):
    db_session.add(
        ClinicChannelSettings(
            clinic_id=test_patient.clinic_id,
            channel="whatsapp",
            adapter_name="whatsapp_evolution",
            is_enabled=False,
            is_verified=False,
        )
    )
    await db_session.commit()

    adapter = await NotificationGateway._adapter_for_channel(
        db_session, test_patient.clinic_id, Channel.WHATSAPP
    )
    assert adapter is None


@pytest.mark.asyncio
async def test_legacy_kapso_clinic_is_not_shadowed_by_evolution_adapter(db_session, test_patient):
    db_session.add(
        WhatsappKapsoSettings(
            clinic_id=test_patient.clinic_id,
            api_key_encrypted=encrypt_password("kapso-key"),
            phone_number_id="PNID-LEGACY",
            webhook_secret_encrypted=encrypt_password("kapso-webhook-secret"),
            is_active=True,
        )
    )
    await db_session.commit()

    adapter = await NotificationGateway._adapter_for_channel(
        db_session, test_patient.clinic_id, Channel.WHATSAPP
    )
    assert adapter is not None
    assert adapter.adapter_name == "whatsapp_kapso"


@pytest.mark.asyncio
async def test_permanent_failure_consumes_retry_budget(db_session, test_patient):
    msg = CommunicationMessage(
        clinic_id=test_patient.clinic_id,
        channel="whatsapp",
        to_address=test_patient.phone,
        patient_id=test_patient.id,
        template_key="prescription",
        message_kind="text",
        status="sending",
        attempts=1,
        max_attempts=5,
    )
    db_session.add(msg)
    await db_session.commit()

    await NotificationGateway._mark_failed(
        db_session,
        msg,
        "permanent provider failure",
        retryable=False,
    )
    assert msg.status == "failed"
    assert msg.attempts == 5
    assert msg.next_attempt_at is None
