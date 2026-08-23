"""Three-message WhatsApp automation for scheduled appointments.

The notifications module owns communication policy.  The WhatsApp provider
module remains a thin channel adapter; this orchestration only uses the public
notification gateway/service seams.

For an appointment whose clinic routes the relevant notification type through
WhatsApp and whose patient has opted in, the automation sends exactly three
proactive template messages:

1. appointment confirmation when ``appointment.scheduled`` is published;
2. the normal appointment reminder (24h by default, clinic configurable);
3. a final WhatsApp reminder 2h before the appointment.

Patients who are not WhatsApp-eligible retain the existing email confirmation
and single reminder behavior.  Every automated WhatsApp message is idempotent
per appointment start time so rescheduling creates a new logical sequence while
scheduler retries cannot duplicate a message.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker

from .channels import Channel, channel_registry
from .gateway import NotificationGateway
from .models import ClinicNotificationSettings, CommunicationMessage
from .service import NotificationService, resolve_clinic_communication_locale

logger = logging.getLogger(__name__)

_FINAL_REMINDER_HOURS = 2


def _dedup_key(kind: str, appointment_id: UUID, start_time: datetime) -> str:
    """Return an idempotency key that changes when an appointment is rescheduled."""
    return f"whatsapp_appointment_{kind}:{appointment_id}:{start_time.isoformat()}"


def _reminder_stage(
    start_time: datetime,
    now: datetime,
    first_hours_before: int,
) -> tuple[str, int] | None:
    """Return the one reminder stage due at ``now``.

    The final window wins over the first reminder window.  This prevents two
    reminders being queued together when a new appointment is created less than
    two hours before its start.
    """
    if start_time <= now:
        return None
    remaining = start_time - now
    if remaining <= timedelta(hours=_FINAL_REMINDER_HOURS):
        return ("final", _FINAL_REMINDER_HOURS)
    if remaining <= timedelta(hours=first_hours_before):
        return ("first", first_hours_before)
    return None


async def _whatsapp_ready(
    db: AsyncSession,
    clinic_id: UUID,
    patient: Any,
    notification_type: str,
) -> bool:
    """Check all proactive-WhatsApp prerequisites without putting a row on the wire."""
    if patient is None or not patient.phone or patient.do_not_contact:
        return False

    clinic_settings = await NotificationService.get_clinic_settings(db, clinic_id)
    type_settings = clinic_settings.settings.get(notification_type, {}) if clinic_settings else {}
    if not type_settings.get("enabled", True) or not type_settings.get("auto_send", True):
        return False
    channels = type_settings.get("channels") or ["email"]
    if "whatsapp" not in channels:
        return False

    prefs = await NotificationService.get_patient_preferences(db, clinic_id, patient.id)
    if prefs is None or not prefs.whatsapp_enabled:
        return False
    if not prefs.preferences.get(notification_type, True):
        return False

    adapter = channel_registry.get_for_channel(Channel.WHATSAPP)
    if adapter is None or not await adapter.supports(db, clinic_id):
        return False

    locale = prefs.preferred_locale or await resolve_clinic_communication_locale(db, clinic_id)
    template = await NotificationService.get_template(
        db,
        clinic_id,
        notification_type,
        locale,
        channel="whatsapp",
    )
    return bool(
        template
        and template.provider_template_status == "approved"
        and template.provider_template_name
    )


async def _already_enqueued(db: AsyncSession, clinic_id: UUID, dedup_key: str) -> bool:
    existing = await db.execute(
        select(CommunicationMessage.id).where(
            CommunicationMessage.clinic_id == clinic_id,
            CommunicationMessage.dedup_key == dedup_key,
        )
    )
    return existing.first() is not None


async def _appointment_context(db: AsyncSession, clinic_id: UUID, appointment: Any, patient: Any):
    from app.core.auth.models import Clinic, User

    clinic = (await db.execute(select(Clinic).where(Clinic.id == clinic_id))).scalar_one_or_none()

    professional_name = None
    if appointment.professional_id:
        professional = (
            await db.execute(select(User).where(User.id == appointment.professional_id))
        ).scalar_one_or_none()
        if professional:
            professional_name = f"{professional.first_name} {professional.last_name}"

    return {
        "patient_name": f"{patient.first_name} {patient.last_name}",
        "appointment_date": appointment.start_time.strftime("%d/%m/%Y"),
        "appointment_time": appointment.start_time.strftime("%H:%M"),
        "professional_name": professional_name,
        "clinic_name": clinic.name if clinic else "Dentora",
        "clinic_phone": clinic.phone if clinic else None,
        "clinic_address": clinic.address if clinic else None,
        "appointment_id": str(appointment.id),
    }


async def enqueue_whatsapp_confirmation(
    db: AsyncSession,
    clinic_id: UUID,
    appointment: Any,
) -> CommunicationMessage | None:
    """Queue the immediate WhatsApp confirmation when the appointment is eligible."""
    from app.modules.patients.models import Patient

    patient = (
        await db.execute(
            select(Patient).where(
                Patient.id == appointment.patient_id,
                Patient.clinic_id == clinic_id,
            )
        )
    ).scalar_one_or_none()
    if not await _whatsapp_ready(db, clinic_id, patient, "appointment_confirmation"):
        return None

    key = _dedup_key("confirmation", appointment.id, appointment.start_time)
    if await _already_enqueued(db, clinic_id, key):
        return None

    context = await _appointment_context(db, clinic_id, appointment, patient)
    return await NotificationGateway.enqueue(
        db=db,
        clinic_id=clinic_id,
        notification_type="appointment_confirmation",
        context=context,
        patient_id=patient.id,
        channels=["whatsapp"],
        force_send=True,
        triggered_by_event="appointment.scheduled",
        dedup_key=key,
    )


async def _handle_appointment_scheduled(data: dict[str, Any]) -> None:
    """Prefer WhatsApp confirmation; preserve the legacy email path as fallback."""
    from app.modules.agenda.models import Appointment
    from app.modules.notifications.handlers import NotificationHandlers

    try:
        clinic_id = UUID(data["clinic_id"])
        appointment_id = UUID(data["appointment_id"])
        whatsapp_eligible = False

        async with async_session_maker() as db:
            appointment = (
                await db.execute(
                    select(Appointment).where(
                        Appointment.id == appointment_id,
                        Appointment.clinic_id == clinic_id,
                    )
                )
            ).scalar_one_or_none()
            if appointment is None:
                logger.error("Appointment not found: %s", appointment_id)
                return

            from app.modules.patients.models import Patient

            patient = (
                await db.execute(
                    select(Patient).where(
                        Patient.id == appointment.patient_id,
                        Patient.clinic_id == clinic_id,
                    )
                )
            ).scalar_one_or_none()
            whatsapp_eligible = await _whatsapp_ready(
                db, clinic_id, patient, "appointment_confirmation"
            )
            if whatsapp_eligible:
                await enqueue_whatsapp_confirmation(db, clinic_id, appointment)

        if not whatsapp_eligible:
            await NotificationHandlers._handle_appointment_scheduled(data)
    except Exception as exc:  # noqa: BLE001 - event handlers must isolate failures
        logger.error("Error handling WhatsApp appointment confirmation: %s", exc, exc_info=True)


def on_appointment_scheduled(data: dict[str, Any]) -> None:
    """Event-bus entry point for the appointment confirmation automation."""
    asyncio.create_task(_handle_appointment_scheduled(data))


async def process_due_appointment_messages(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Queue due reminder messages and return the number of queued rows.

    WhatsApp-eligible patients receive the first and final WhatsApp reminders.
    Everyone else receives only the existing first email reminder.
    """
    from app.core.auth.models import Clinic, User
    from app.modules.agenda.models import Appointment
    from app.modules.patients.models import Patient

    current = now or datetime.now(UTC)
    queued = 0

    settings_rows = (await db.execute(select(ClinicNotificationSettings))).scalars().all()
    for clinic_settings in settings_rows:
        reminder_config = clinic_settings.settings.get("appointment_reminder", {})
        if not reminder_config.get("enabled", True) or not reminder_config.get("auto_send", True):
            continue

        first_hours = int(reminder_config.get("hours_before", 24))
        if first_hours <= _FINAL_REMINDER_HOURS:
            first_hours = 24
        clinic_id = clinic_settings.clinic_id
        appointments = (
            (
                await db.execute(
                    select(Appointment).where(
                        and_(
                            Appointment.clinic_id == clinic_id,
                            Appointment.status == "scheduled",
                            Appointment.start_time > current,
                            Appointment.start_time <= current + timedelta(hours=first_hours),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        if not appointments:
            continue

        clinic = (
            await db.execute(select(Clinic).where(Clinic.id == clinic_id))
        ).scalar_one_or_none()

        for appointment in appointments:
            stage = _reminder_stage(appointment.start_time, current, first_hours)
            if stage is None:
                continue
            stage_name, stage_hours = stage

            patient = (
                await db.execute(
                    select(Patient).where(
                        Patient.id == appointment.patient_id,
                        Patient.clinic_id == clinic_id,
                    )
                )
            ).scalar_one_or_none()
            if patient is None:
                continue

            whatsapp_ready = await _whatsapp_ready(db, clinic_id, patient, "appointment_reminder")
            # The final message is WhatsApp-only.  If WhatsApp is unavailable,
            # preserve the historical single email reminder and do nothing here.
            if stage_name == "final" and not whatsapp_ready:
                continue

            professional_name = None
            if appointment.professional_id:
                professional = (
                    await db.execute(select(User).where(User.id == appointment.professional_id))
                ).scalar_one_or_none()
                if professional:
                    professional_name = f"{professional.first_name} {professional.last_name}"

            context = {
                "patient_name": f"{patient.first_name} {patient.last_name}",
                "appointment_date": appointment.start_time.strftime("%d/%m/%Y"),
                "appointment_time": appointment.start_time.strftime("%H:%M"),
                "professional_name": professional_name,
                "clinic_name": clinic.name if clinic else "Dentora",
                "clinic_phone": clinic.phone if clinic else None,
                "clinic_address": clinic.address if clinic else None,
                "appointment_id": str(appointment.id),
                "reminder_stage": stage_name,
                "reminder_hours_before": stage_hours,
            }

            if whatsapp_ready:
                key = _dedup_key(f"reminder_{stage_name}", appointment.id, appointment.start_time)
                if await _already_enqueued(db, clinic_id, key):
                    continue
                msg = await NotificationGateway.enqueue(
                    db=db,
                    clinic_id=clinic_id,
                    notification_type="appointment_reminder",
                    context=context,
                    patient_id=patient.id,
                    channels=["whatsapp"],
                    force_send=True,
                    triggered_by_event="scheduler.whatsapp_appointment_reminder",
                    dedup_key=key,
                )
            else:
                # First-stage fallback is intentionally the old email behavior.
                if not patient.email:
                    continue
                key = f"appointment_reminder:{appointment.id}"
                if await _already_enqueued(db, clinic_id, key):
                    continue
                msg = await NotificationGateway.enqueue(
                    db=db,
                    clinic_id=clinic_id,
                    notification_type="appointment_reminder",
                    context=context,
                    patient_id=patient.id,
                    to_address=patient.email,
                    channels=["email"],
                    force_send=True,
                    triggered_by_event="scheduler.appointment_reminder",
                    dedup_key=key,
                )

            if msg is not None and msg.status != "skipped":
                queued += 1

    return queued


async def process_appointment_message_automation() -> None:
    """Scheduled five-minute tick for the three-message appointment sequence."""
    try:
        async with async_session_maker() as db:
            queued = await process_due_appointment_messages(db)
            if queued:
                logger.info("Appointment message automation queued %d message(s)", queued)
    except Exception as exc:  # noqa: BLE001 - scheduled jobs must not crash the scheduler
        logger.error("Appointment message automation failed: %s", exc, exc_info=True)
