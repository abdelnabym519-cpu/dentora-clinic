"""Map ``recall`` (Gesdén ``Recalls``) → :class:`recalls.Recall`.

The Gesdén ``Recalls`` table is a flat call-back queue with one row per
scheduled follow-up. ``IdMotivo`` (reason) and ``IdResultado`` (result)
are surfaced in the canonical payload as opaque uuid5 references —
without a master decoder for those uuids we can't map back to the
Dentora reason vocabulary. The mapper therefore drops the row into
``other`` and stores the free-text ``Comentario`` in ``reason_note``
so the receptionist still has context.

Status derivation:

- ``attended=True``       → ``done`` (completed_at = contact_date or scheduled_date)
- ``status_code==1``      → ``done`` (Gesdén "asistido" flag drift)
- ``scheduled=True``      → ``contacted_scheduled``
- ``contact_date``        → ``contacted_no_answer`` (we logged an attempt, no booking)
- else                    → ``pending``

Idempotent: re-running the mapper short-circuits via the resolver.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.modules.recalls.models import Recall

from ..models import ImportWarning
from .base import MapperContext

logger = logging.getLogger(__name__)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _derive_status(payload: dict[str, Any]) -> str:
    if payload.get("attended") or payload.get("status_code") == 1:
        return "done"
    if payload.get("scheduled"):
        return "contacted_scheduled"
    if payload.get("contact_date"):
        return "contacted_no_answer"
    return "pending"


def _due_month(scheduled: date | None) -> date:
    base = scheduled or date.today()
    return base.replace(day=1)


def _reason_note(payload: dict[str, Any]) -> str | None:
    parts = [payload.get("comments"), payload.get("observations")]
    text = "\n".join(p for p in parts if p)
    return text[:4000] if text else None


class RecallMapper:
    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        existing = await ctx.resolver.get("recall", canonical_uuid)
        if existing is not None:
            return existing

        patient_uuid = payload.get("patient_uuid")
        if not patient_uuid:
            await _warn(
                ctx,
                source_id,
                "recall.missing_patient",
                "Recall omitido: sin patient_uuid en origen.",
            )
            return None
        patient_id = await ctx.resolver.get("patient", str(patient_uuid))
        if patient_id is None:
            await _warn(
                ctx,
                source_id,
                "recall.unmapped_patient",
                f"Recall omitido: paciente {patient_uuid} no migrado.",
            )
            return None

        professional_uuid = payload.get("professional_uuid")
        assigned_id: UUID | None = None
        if professional_uuid:
            assigned_id = await ctx.resolver.get("professional", str(professional_uuid))

        scheduled = _parse_date(payload.get("scheduled_date"))
        contact_dt = _parse_datetime(payload.get("contact_date")) or _parse_datetime(
            (raw or {}).get("FechaContacto")
        )

        status = _derive_status(payload)
        completed_at = contact_dt if status == "done" else None
        attempt_count = 1 if contact_dt else 0

        recall = Recall(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            due_month=_due_month(scheduled),
            due_date=scheduled,
            reason="other",
            reason_note=_reason_note(payload),
            priority="normal",
            status=status,
            assigned_professional_id=assigned_id,
            last_contact_attempt_at=contact_dt,
            contact_attempt_count=attempt_count,
            completed_at=completed_at,
        )
        ctx.db.add(recall)
        await ctx.db.flush()

        await ctx.resolver.set(
            entity_type="recall",
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dentora_table="recalls",
            dentora_id=recall.id,
        )
        return recall.id


async def _warn(ctx: MapperContext, source_id: str, code: str, message: str) -> None:
    ctx.db.add(
        ImportWarning(
            job_id=ctx.job_id,
            entity_type="recall",
            source_id=source_id,
            severity="info",
            code=code,
            message=message,
        )
    )
