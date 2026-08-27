"""Electronic Prescription WhatsApp delivery integration tests."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.auth.models import User
from app.core.email.encryption import encrypt_password
from app.modules.notifications.models import NotificationPreference, NotificationTemplate
from app.modules.prescriptions.delivery import list_whatsapp_deliveries, queue_whatsapp_delivery
from app.modules.prescriptions.domain import MedicationItem, Prescription, PrescriptionStatus
from app.modules.whatsapp_kapso.models import WhatsappKapsoSettings


def _issued_rx(clinic_id, patient_id, doctor_id) -> Prescription:
    now = datetime.now(UTC)
    return Prescription(
        id=uuid4(),
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        clinic_id=clinic_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        identifier="RX-20260827-TEST00000001",
        status=PrescriptionStatus.ISSUED,
        items=(
            MedicationItem(
                medication_name="Amoxicillin",
                strength="500 mg",
                dose="1 capsule",
                frequency="every 8 hours",
                duration="5 days",
                route="oral",
                instructions="after food",
                quantity=15,
                quantity_unit="capsules",
            ),
        ),
        created_at=now,
        updated_at=now,
        issued_at=now,
    )


async def _actor(db_session) -> User:
    return (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()


async def _enable_whatsapp(db_session, clinic_id, patient_id) -> None:
    db_session.add(
        WhatsappKapsoSettings(
            clinic_id=clinic_id,
            api_key_encrypted=encrypt_password("api-key"),
            phone_number_id="PNID",
            business_account_id="WABA",
            webhook_secret_encrypted=encrypt_password("secret"),
            is_active=True,
            is_verified=True,
        )
    )
    db_session.add(
        NotificationPreference(
            clinic_id=clinic_id,
            patient_id=patient_id,
            whatsapp_enabled=True,
            preferred_locale="es",
        )
    )
    db_session.add(
        NotificationTemplate(
            clinic_id=clinic_id,
            channel="whatsapp",
            template_key="prescription_issued",
            locale="es",
            provider_template_name="dentora_prescription_issued",
            provider_template_status="approved",
            is_active=True,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_issued_prescription_queues_once_and_is_trackable(
    db_session, test_clinic, test_patient
):
    actor = await _actor(db_session)
    await _enable_whatsapp(db_session, test_clinic.id, test_patient.id)
    rx = _issued_rx(test_clinic.id, test_patient.id, actor.id)

    first = await queue_whatsapp_delivery(db_session, rx, actor_user_id=actor.id)
    second = await queue_whatsapp_delivery(db_session, rx, actor_user_id=actor.id)

    assert first.id == second.id
    assert first.channel == "whatsapp"
    assert first.status == "queued"
    assert first.to_address == test_patient.phone
    assert first.context_data["_prescription_id"] == str(rx.id)
    assert first.context_data["prescription_identifier"] == rx.identifier
    assert "Amoxicillin" in first.context_data["medications"]

    history = await list_whatsapp_deliveries(db_session, rx)
    assert [row.id for row in history] == [first.id]


@pytest.mark.asyncio
async def test_skipped_delivery_is_audited_and_can_retry_after_configuration(
    db_session, test_clinic, test_patient
):
    actor = await _actor(db_session)
    rx = _issued_rx(test_clinic.id, test_patient.id, actor.id)

    skipped = await queue_whatsapp_delivery(db_session, rx, actor_user_id=actor.id)
    assert skipped.status == "skipped"
    assert skipped.channel == "whatsapp"
    assert skipped.to_address == test_patient.phone
    assert skipped.context_data["_prescription_id"] == str(rx.id)

    await _enable_whatsapp(db_session, test_clinic.id, test_patient.id)
    retried = await queue_whatsapp_delivery(db_session, rx, actor_user_id=actor.id)

    assert retried.id != skipped.id
    assert retried.status == "queued"
    history = await list_whatsapp_deliveries(db_session, rx)
    assert [row.status for row in history] == ["queued", "skipped"]
