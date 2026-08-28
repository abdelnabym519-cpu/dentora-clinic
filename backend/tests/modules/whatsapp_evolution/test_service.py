"""Evolution provider selector lifecycle tests."""

import pytest
from sqlalchemy import select

from app.core.email.encryption import encrypt_password
from app.modules.notifications.models import ClinicChannelSettings
from app.modules.whatsapp_evolution.models import WhatsappEvolutionSettings
from app.modules.whatsapp_evolution.service import EvolutionService


def _settings(clinic_id, *, active=True, verified=False):
    return WhatsappEvolutionSettings(
        clinic_id=clinic_id,
        base_url="http://evolution.test:8080",
        instance_name="clinic-a",
        api_key_encrypted=encrypt_password("api-key"),
        webhook_token_encrypted=encrypt_password("webhook-token"),
        is_active=active,
        is_verified=verified,
    )


async def _selector(db, clinic_id):
    return (
        await db.execute(
            select(ClinicChannelSettings).where(
                ClinicChannelSettings.clinic_id == clinic_id,
                ClinicChannelSettings.channel == "whatsapp",
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_unverified_evolution_does_not_claim_empty_channel(db_session, test_clinic):
    settings = _settings(test_clinic.id, verified=False)
    await EvolutionService._sync_channel_selector(db_session, settings)
    await db_session.commit()
    assert await _selector(db_session, test_clinic.id) is None


@pytest.mark.asyncio
async def test_unverified_evolution_does_not_replace_kapso_selector(db_session, test_clinic):
    row = ClinicChannelSettings(
        clinic_id=test_clinic.id,
        channel="whatsapp",
        adapter_name="whatsapp_kapso",
        is_enabled=True,
        is_verified=True,
    )
    db_session.add(row)
    await db_session.commit()

    settings = _settings(test_clinic.id, verified=False)
    await EvolutionService._sync_channel_selector(db_session, settings)
    await db_session.commit()
    await db_session.refresh(row)

    assert row.adapter_name == "whatsapp_kapso"
    assert row.is_enabled is True
    assert row.is_verified is True


@pytest.mark.asyncio
async def test_verified_evolution_is_explicit_cutover_point(db_session, test_clinic):
    row = ClinicChannelSettings(
        clinic_id=test_clinic.id,
        channel="whatsapp",
        adapter_name="whatsapp_kapso",
        is_enabled=True,
        is_verified=True,
    )
    db_session.add(row)
    await db_session.commit()

    settings = _settings(test_clinic.id, verified=True)
    await EvolutionService._sync_channel_selector(db_session, settings)
    await db_session.commit()
    await db_session.refresh(row)

    assert row.adapter_name == "whatsapp_evolution"
    assert row.is_enabled is True
    assert row.is_verified is True
    assert row.config == {
        "base_url": "http://evolution.test:8080",
        "instance_name": "clinic-a",
    }


@pytest.mark.asyncio
async def test_selected_evolution_disconnect_remains_fail_closed(db_session, test_clinic):
    row = ClinicChannelSettings(
        clinic_id=test_clinic.id,
        channel="whatsapp",
        adapter_name="whatsapp_evolution",
        is_enabled=True,
        is_verified=True,
    )
    db_session.add(row)
    await db_session.commit()

    settings = _settings(test_clinic.id, verified=False)
    await EvolutionService._sync_channel_selector(db_session, settings)
    await db_session.commit()
    await db_session.refresh(row)

    assert row.adapter_name == "whatsapp_evolution"
    assert row.is_enabled is True
    assert row.is_verified is False


@pytest.mark.asyncio
async def test_disabling_selected_evolution_relinquishes_selector(db_session, test_clinic):
    row = ClinicChannelSettings(
        clinic_id=test_clinic.id,
        channel="whatsapp",
        adapter_name="whatsapp_evolution",
        is_enabled=True,
        is_verified=True,
    )
    db_session.add(row)
    await db_session.commit()

    settings = _settings(test_clinic.id, active=False, verified=False)
    await EvolutionService._sync_channel_selector(db_session, settings)
    await db_session.commit()

    assert await _selector(db_session, test_clinic.id) is None
