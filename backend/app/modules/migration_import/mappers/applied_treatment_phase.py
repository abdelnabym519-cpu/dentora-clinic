"""Map ``applied_treatment_phase`` → :class:`treatment_plan.PlannedTreatmentItemSession`.

Each canonical phase becomes one session attached to the
``PlannedTreatmentItem`` produced by :class:`AppliedTreatmentMapper`.

A canonical phase carries `percent_to_bill` (a 0-100 fraction of the
parent treatment that this phase represents). We don't currently model
that exactly — sessions carry an explicit absolute `amount`. The
migration writes the phase's percent as a metadata note and leaves the
amount at zero; clinics can rebalance after import.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.modules.treatment_plan.models import (
    PlannedTreatmentItem,
    PlannedTreatmentItemSession,
)

from ..models import ImportWarning
from .base import MapperContext

# Mirrors ``AppliedTreatmentMapper._REALISED_CODES`` — both StaTto
# values (5 dominant, 6 variant) carry ``FecFin`` in the source and
# correspond to a completed treatment.
_REALISED_CODES: set[int] = {5, 6}


class AppliedTreatmentPhaseMapper:
    def __init__(self) -> None:
        # plan_item_id -> next sequence to assign. The migrated parent
        # plan item starts with no sessions; phases append in order.
        self._next_sequence: dict[UUID, int] = {}

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
        existing = await ctx.resolver.get("applied_treatment_phase", canonical_uuid)
        if existing is not None:
            return existing
        if await ctx.resolver.was_skipped("applied_treatment_phase", canonical_uuid):
            return None

        parent_uuid = payload.get("applied_treatment_uuid")
        if not parent_uuid:
            await _warn(ctx, source_id, "phase.no_parent", "Fase sin tratamiento padre.")
            await ctx.resolver.mark_skipped(
                "applied_treatment_phase", canonical_uuid, source_system
            )
            return None

        plan_item_id = await ctx.resolver.get("applied_treatment", str(parent_uuid))
        if plan_item_id is None:
            await _warn(
                ctx,
                source_id,
                "phase.unmapped_parent",
                "Fase omitida: tratamiento padre no mapeado.",
            )
            await ctx.resolver.mark_skipped(
                "applied_treatment_phase", canonical_uuid, source_system
            )
            return None

        # Seed the per-item sequence counter on first phase by querying
        # any pre-existing sessions (idempotent re-runs).
        sequence = self._next_sequence.get(plan_item_id)
        if sequence is None:
            result = await ctx.db.execute(
                select(PlannedTreatmentItemSession.sequence)
                .where(PlannedTreatmentItemSession.plan_item_id == plan_item_id)
                .order_by(PlannedTreatmentItemSession.sequence.desc())
                .limit(1)
            )
            existing_max = result.scalar_one_or_none() or 0
            sequence = existing_max
        sequence += 1
        self._next_sequence[plan_item_id] = sequence

        # The Gesdén phase row carries its own ``StaTto`` but in the
        # observed data it never takes the completed codes (it stays
        # 1/3 even when the parent treatment is finished). The clinic-
        # facing source of truth for completion is the parent
        # ``TtosMed`` row, so we mirror the parent ``PlannedTreatmentItem``
        # status: sessions of a completed item are completed.
        status_code = payload.get("status_code")
        try:
            sc_int = int(status_code) if status_code is not None else None
        except (TypeError, ValueError):
            sc_int = None
        phase_realised = sc_int in _REALISED_CODES
        parent_status = await ctx.db.execute(
            select(PlannedTreatmentItem.status).where(PlannedTreatmentItem.id == plan_item_id)
        )
        parent_status_value = parent_status.scalar_one_or_none()
        is_realised = phase_realised or parent_status_value == "completed"
        executed_dt = _parse_datetime(payload.get("executed_on"))

        # We don't yet split the parent treatment's amount across phases
        # — Dentora sessions carry absolute amounts and we lack the
        # canonical price split. Leave amount at zero and surface the
        # source percent in the label for visibility.
        label_parts: list[str] = []
        phase_num = payload.get("phase_number")
        if phase_num:
            label_parts.append(f"Fase {phase_num}")
        percent = payload.get("percent_to_bill")
        if percent:
            label_parts.append(f"{percent}%")
        label = " · ".join(label_parts) or None

        prof_id: UUID | None = None
        prof_uuid = payload.get("professional_uuid")
        if prof_uuid:
            prof_id = await ctx.resolver.get("professional", str(prof_uuid))

        session = PlannedTreatmentItemSession(
            plan_item_id=plan_item_id,
            sequence=sequence,
            label=label,
            amount=Decimal("0.00"),
            status="completed" if is_realised else "pending",
            completed_at=executed_dt if is_realised else None,
            completed_by=prof_id if is_realised else None,
            notes=payload.get("notes"),
        )
        ctx.db.add(session)
        await ctx.db.flush()

        # Refresh the parent item's status if all sessions terminal.
        # Skipped — the treatment_plan module's natural finalisation
        # logic does that on real completion; for migrated data we
        # already set the parent's status in the applied_treatment
        # mapper based on the source status_code.
        _ = PlannedTreatmentItem  # imported only for clarity in docs

        await ctx.resolver.set(
            entity_type="applied_treatment_phase",
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dentora_table="planned_treatment_item_sessions",
            dentora_id=session.id,
        )
        return session.id


async def _warn(ctx: MapperContext, source_id: str, code: str, message: str) -> None:
    ctx.db.add(
        ImportWarning(
            job_id=ctx.job_id,
            entity_type="applied_treatment_phase",
            source_id=source_id,
            severity="warn",
            code=code,
            message=message,
        )
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        try:
            d = date.fromisoformat(str(value)[:10])
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        except (TypeError, ValueError):
            return None
