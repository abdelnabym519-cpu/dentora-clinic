"""WhatsApp delivery integration for issued electronic prescriptions.

The prescriptions module owns the delivery intent and read model while the
notifications module owns consent, channel resolution, outbox retry, provider
status and webhook delivery receipts. No provider SDK is imported here.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.gateway import NotificationGateway
from app.modules.notifications.models import CommunicationMessage
from app.modules.patients.models import Patient

from .domain import Prescription, PrescriptionError, PrescriptionStatus

PRESCRIPTION_NOTIFICATION_TYPE = "prescription_issued"
_ACTIVE_DELIVERY_STATUSES = {"queued", "sending", "sent", "delivered", "read"}


def _medication_summary(rx: Prescription, *, max_chars: int = 900) -> str:
    """Compact deterministic medication text suitable for a WhatsApp template."""
    parts: list[str] = []
    for item in rx.items:
        detail = f"{item.medication_name}: {item.dose}, {item.frequency}, {item.duration}"
        if item.route:
            detail += f", {item.route}"
        parts.append(detail)
    summary = "; ".join(parts)
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "…"


async def list_whatsapp_deliveries(
    db: AsyncSession,
    rx: Prescription,
) -> Sequence[CommunicationMessage]:
    """Return this prescription's WhatsApp delivery history, newest first."""
    rows = (
        (
            await db.execute(
                select(CommunicationMessage)
                .where(
                    CommunicationMessage.clinic_id == rx.clinic_id,
                    CommunicationMessage.patient_id == rx.patient_id,
                    CommunicationMessage.channel == "whatsapp",
                    CommunicationMessage.template_key == PRESCRIPTION_NOTIFICATION_TYPE,
                )
                .order_by(CommunicationMessage.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    prescription_id = str(rx.id)
    return [
        row
        for row in rows
        if (row.context_data or {}).get("_prescription_id") == prescription_id
    ]


async def queue_whatsapp_delivery(
    db: AsyncSession,
    rx: Prescription,
    *,
    actor_user_id: UUID,
) -> CommunicationMessage:
    """Queue (or reuse) WhatsApp delivery for an issued prescription.

    Delivery is idempotent while an earlier attempt is queued/in-flight/successful.
    A new attempt is allowed after a terminal ``failed``/``skipped`` result so a
    clinic can fix credentials/template/consent and retry without editing the
    immutable prescription.
    """
    if rx.status != PrescriptionStatus.ISSUED:
        raise PrescriptionError("only issued prescriptions can be delivered")

    history = list(await list_whatsapp_deliveries(db, rx))
    for existing in history:
        if existing.status in _ACTIVE_DELIVERY_STATUSES:
            return existing

    patient = (
        await db.execute(
            select(Patient).where(
                Patient.id == rx.patient_id,
                Patient.clinic_id == rx.clinic_id,
            )
        )
    ).scalar_one_or_none()
    if patient is None:
        raise PrescriptionError("patient is not available in the selected clinic")

    attempt = len(history) + 1
    context = {
        "patient_name": patient.full_name,
        "prescription_identifier": rx.identifier,
        "medications": _medication_summary(rx),
        "issued_at": rx.issued_at.isoformat() if rx.issued_at else "",
        # Internal correlation value: stored in the outbox/audit row but never
        # forwarded as a Meta template variable (Kapso skips '_' keys).
        "_prescription_id": str(rx.id),
    }
    message = await NotificationGateway.enqueue(
        db,
        rx.clinic_id,
        PRESCRIPTION_NOTIFICATION_TYPE,
        context=context,
        patient_id=rx.patient_id,
        channels=["whatsapp"],
        force_send=True,
        triggered_by_event="prescription.issued",
        triggered_by_user_id=actor_user_id,
        dedup_key=f"prescription:{rx.id}:whatsapp:{attempt}",
    )
    if message is None:
        # A concurrent identical enqueue won the unique dedup race. Re-read the
        # history and return the persisted source of truth.
        refreshed = await list_whatsapp_deliveries(db, rx)
        if refreshed:
            return refreshed[0]
        raise RuntimeError("prescription WhatsApp delivery deduplication failed")
    return message
