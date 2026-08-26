"""Read-only Implant Planning output adapter for Case Intelligence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dental_3d.implant_models import DentalImplantPlan, DentalImplantPlanRevision

from .contracts import AvailabilityStatus
from .source_common import data, evidence, section


async def collect_implant_sources(
    db: AsyncSession,
    clinic_id: UUID,
    patient_id: UUID,
    *,
    accepted_alignment_id: UUID | None,
) -> dict[str, Any]:
    plans = (
        await db.scalars(
            select(DentalImplantPlan)
            .where(
                DentalImplantPlan.clinic_id == clinic_id,
                DentalImplantPlan.patient_id == patient_id,
            )
            .order_by(DentalImplantPlan.created_at, DentalImplantPlan.id)
        )
    ).all()
    payloads: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    stale = False
    for plan in plans:
        revision = await db.scalar(
            select(DentalImplantPlanRevision).where(
                DentalImplantPlanRevision.plan_id == plan.id,
                DentalImplantPlanRevision.revision_number == plan.current_revision_number,
            )
        )
        if revision is None:
            stale = True
            stale_payload = data(plan, "id", "status", "current_revision_number")
            refs.append(
                evidence(
                    "dental_3d",
                    "DentalImplantPlan",
                    plan.id,
                    stale_payload,
                    version=str(plan.current_revision_number),
                    validation_state="missing_current_revision",
                )
            )
            continue

        payload = {
            "plan_id": plan.id,
            **data(plan, "status", "current_revision_number", "reviewed_at"),
            "revision": data(
                revision,
                "id",
                "revision_number",
                "candidate",
                "assessment",
                "planning_case",
                "policy",
                "created_at",
            ),
        }
        payloads.append(payload)
        refs.append(
            evidence(
                "dental_3d",
                "DentalImplantPlanRevision",
                revision.id,
                payload,
                version=str(revision.revision_number),
                validation_state=plan.status,
            )
        )
        planning_case = revision.planning_case or {}
        revision_alignment_id = planning_case.get("alignment_id")
        if (
            accepted_alignment_id is not None
            and revision_alignment_id is not None
            and str(revision_alignment_id) != str(accepted_alignment_id)
        ):
            stale = True

    if stale:
        return section(
            AvailabilityStatus.INVALID_OR_STALE,
            data_value={"plans": payloads},
            evidence_value=refs,
            reason="implant_planning_current_revision_missing_or_alignment_stale",
        )
    if payloads:
        return section(
            AvailabilityStatus.AVAILABLE,
            data_value={"plans": payloads},
            evidence_value=refs,
        )
    return section(
        AvailabilityStatus.NOT_AVAILABLE,
        reason="implant_planning_not_available",
    )
