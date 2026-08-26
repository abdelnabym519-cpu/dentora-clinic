"""Regression tests for the WhatsApp three-message appointment automation."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.auth.models import ClinicMembership
from app.modules.agenda.models import Appointment
from app.modules.notifications.channels import (
    AdapterResult,
    Channel,
    SendStatus,
    channel_registry,
)
from app.modules.notifications.models import (
    ClinicNotificationSettings,
    CommunicationMessage,
    NotificationPreference,
    NotificationTemplate,
)
from app.modules.notifications.whatsapp_automation import (
    _reminder_stage,
    enqueue_whatsapp_confirmation,
    process_due_appointment_messages,
)


@pytest_asyncio.fixture
async def whatsapp_adapter():
    class FakeWhatsApp:
        channel = Channel.WHATSAPP
        adapter_name = "fake_whatsapp_automation"

        async def supports(self, db, clinic_id):  # noqa: ARG002
            return True

        async def send(self, db, msg):  # noqa: ARG002
            return AdapterResult(
                status=SendStatus.SENT,
                provider="fake_whatsapp",
                provider_message_id="wamid.automation",
            )

    adapter = FakeWhatsApp()
    channel_registry.register(adapter)
    yield adapter
    channel_registry.unregister("fake_whatsapp_automation")


async def _enable_whatsapp_appointment_messages(db_session, test_patient) -> None:
    db_session.add(
        ClinicNotificationSettings(
            clinic_id=test_patient.clinic_id,
            settings={
                "appointment_confirmation": {
                    "enabled": True,
                    "auto_send": True,
                    "channels": ["whatsapp", "email"],
                },
                "appointment_reminder": {
                    "enabled": True,
                    "auto_send": True,
                    "hours_before": 24,
                    "channels": ["whatsapp", "email"],
                },
            },
        )
    )
    db_session.add(
        NotificationPreference(
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            email_enabled=True,
            whatsapp_enabled=True,
            preferences={
                "appointment_confirmation": True,
                "appointment_reminder": True,
            },
            preferred_locale="es",
        )
    )
    for template_key in ("appointment_confirmation", "appointment_reminder"):
        db_session.add(
            NotificationTemplate(
                clinic_id=test_patient.clinic_id,
                channel="whatsapp",
                template_key=template_key,
                locale="es",
                provider_template_name=f"dentora_{template_key}",
                provider_template_status="approved",
                is_system=False,
                is_active=True,
            )
        )
    await db_session.commit()


def test_reminder_stage_uses_one_window_at_a_time() -> None:
    now = datetime(2026, 8, 23, 8, 0, tzinfo=UTC)

    assert _reminder_stage(now + timedelta(hours=25), now, 24) is None
    assert _reminder_stage(now + timedelta(hours=3), now, 24) == ("first", 24)
    assert _reminder_stage(now + timedelta(hours=2), now, 24) == ("final", 2)
    assert _reminder_stage(now + timedelta(minutes=30), now, 24) == ("final", 2)
    assert _reminder_stage(now, now, 24) is None


@pytest.mark.asyncio
async def test_confirmation_is_whatsapp_and_idempotent(
    db_session,
    test_patient,
    whatsapp_adapter,
) -> None:
    await _enable_whatsapp_appointment_messages(db_session, test_patient)
    appointment = SimpleNamespace(
        id=uuid4(),
        patient_id=test_patient.id,
        professional_id=None,
        start_time=datetime.now(UTC) + timedelta(days=2),
    )

    first = await enqueue_whatsapp_confirmation(
        db_session,
        test_patient.clinic_id,
        appointment,
    )
    second = await enqueue_whatsapp_confirmation(
        db_session,
        test_patient.clinic_id,
        appointment,
    )

    assert first is not None
    assert first.status == "queued"
    assert first.channel == "whatsapp"
    assert first.template_key == "appointment_confirmation"
    assert second is None


@pytest.mark.asyncio
async def test_scheduler_queues_first_then_final_whatsapp_reminder_once(
    db_session,
    test_patient,
    whatsapp_adapter,
) -> None:
    await _enable_whatsapp_appointment_messages(db_session, test_patient)
    membership = (
        await db_session.execute(
            select(ClinicMembership).where(ClinicMembership.clinic_id == test_patient.clinic_id)
        )
    ).scalar_one()
    now = datetime.now(UTC).replace(microsecond=0)
    appointment = Appointment(
        id=uuid4(),
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        professional_id=membership.user_id,
        start_time=now + timedelta(hours=3),
        end_time=now + timedelta(hours=4),
        status="scheduled",
    )
    db_session.add(appointment)
    await db_session.commit()

    assert await process_due_appointment_messages(db_session, now=now) == 1
    assert await process_due_appointment_messages(db_session, now=now) == 0

    final_now = now + timedelta(hours=1, minutes=30)
    assert await process_due_appointment_messages(db_session, now=final_now) == 1
    assert await process_due_appointment_messages(db_session, now=final_now) == 0

    messages = list(
        (
            await db_session.execute(
                select(CommunicationMessage)
                .where(
                    CommunicationMessage.clinic_id == test_patient.clinic_id,
                    CommunicationMessage.template_key == "appointment_reminder",
                )
                .order_by(CommunicationMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert len(messages) == 2
    assert [message.channel for message in messages] == ["whatsapp", "whatsapp"]
    assert [message.context_data["reminder_stage"] for message in messages] == [
        "first",
        "final",
    ]
    assert messages[0].dedup_key != messages[1].dedup_key


@pytest.mark.asyncio
async def test_scheduler_preserves_single_email_fallback_without_whatsapp_opt_in(
    db_session,
    test_patient,
) -> None:
    db_session.add(
        ClinicNotificationSettings(
            clinic_id=test_patient.clinic_id,
            settings={
                "appointment_reminder": {
                    "enabled": True,
                    "auto_send": True,
                    "hours_before": 24,
                    "channels": ["email"],
                }
            },
        )
    )
    db_session.add(
        NotificationTemplate(
            clinic_id=test_patient.clinic_id,
            channel="email",
            template_key="appointment_reminder",
            locale="es",
            subject="Reminder",
            body_html="<p>{{patient_name}}</p>",
            is_system=False,
            is_active=True,
        )
    )
    await db_session.commit()

    membership = (
        await db_session.execute(
            select(ClinicMembership).where(ClinicMembership.clinic_id == test_patient.clinic_id)
        )
    ).scalar_one()
    now = datetime.now(UTC).replace(microsecond=0)
    appointment = Appointment(
        id=uuid4(),
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        professional_id=membership.user_id,
        start_time=now + timedelta(hours=3),
        end_time=now + timedelta(hours=4),
        status="scheduled",
    )
    db_session.add(appointment)
    await db_session.commit()

    assert await process_due_appointment_messages(db_session, now=now) == 1
    assert (
        await process_due_appointment_messages(
            db_session,
            now=now + timedelta(hours=1, minutes=30),
        )
        == 0
    )

    messages = list(
        (
            await db_session.execute(
                select(CommunicationMessage).where(
                    CommunicationMessage.clinic_id == test_patient.clinic_id,
                    CommunicationMessage.template_key == "appointment_reminder",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(messages) == 1
    assert messages[0].channel == "email"
