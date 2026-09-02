"""Orthodontic planning service — orchestrates providers + the safety gate.

Responsibilities:

1. Build immutable case inputs: patient scoping (clinic-tenant check),
   a read-only dentition snapshot from the odontogram, and the
   deterministic data-sufficiency report.
2. Resolve the configured :class:`PlanningProvider` (fail-closed 503 on
   unknown/broken providers).
3. **Independently re-validate** every provider suggestion through
   :func:`constraints.evaluate_stages`. A suggestion with a hard
   violation is *refused* (never persisted), an audit event is emitted,
   and the API surfaces the refusal — the model can never write an
   unsafe plan into the database.
4. Persist valid proposals as ``draft`` and emit audit events for
   creation, review, and refusal (ids only — no clinical payload).
5. Enforce the review lifecycle: draft → approved/rejected by a user
   holding ``orthodontic_planning.write``; no other transition exists,
   and nothing in this module consumes an approval autonomously.

Coupling policy: ``patients`` and ``odontogram`` are declared module
dependencies and are only ever *read* (plain queries); no cross-module
FKs beyond patients/clinics/users. The odontogram snapshot is copied
JSONB so uninstall remains clean.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import event_bus
from app.core.events.types import EventType
from app.modules.odontogram.models import ToothRecord
from app.modules.patients.models import Patient

from .constants import (
    CONSTRAINTS_VERSION,
    MISSING_TOOTH_CONDITIONS,
    STAGE_INTERVAL_WEEKS,
    STATUS_DRAFT,
    WEEKS_PER_MONTH,
)
from .constraints import evaluate_stages
from .domain import (
    DentitionSnapshot,
    PlannerCase,
    ToothSnapshot,
    build_sufficiency,
)
from .models import OrthoAssessment, OrthoPlanProposal
from .planner import PlanningProvider, get_provider
from .planner.base import InsufficientDataError


class ProviderFailureError(RuntimeError):
    """A provider raised while proposing (fail-closed, nothing stored)."""


class PlanningRefusedError(RuntimeError):
    """A provider suggestion failed the deterministic safety gate.

    Carries the constraint report; the router maps this to HTTP 422
    and the service has already emitted the refusal audit event. The
    refused plan is deliberately NOT persisted.
    """

    def __init__(self, report) -> None:
        self.report = report
        super().__init__("Planner output refused by the deterministic safety gate")


class OrthodonticPlanningService:
    """Thin service over providers, the safety gate, and persistence."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # --- shared lookups -------------------------------------------------------

    async def get_patient(self, clinic_id: UUID, patient_id: UUID) -> Patient | None:
        stmt = select(Patient).where(
            Patient.id == patient_id,
            Patient.clinic_id == clinic_id,
            Patient.status != "archived",
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def _load_dentition(self, clinic_id: UUID, patient_id: UUID) -> DentitionSnapshot:
        """Read-only odontogram snapshot (values copied; no ORM objects escape)."""
        stmt = select(
            ToothRecord.tooth_number,
            ToothRecord.tooth_type,
            ToothRecord.general_condition,
            ToothRecord.is_displaced,
            ToothRecord.is_rotated,
        ).where(
            ToothRecord.clinic_id == clinic_id,
            ToothRecord.patient_id == patient_id,
        )
        rows = (await self._db.execute(stmt)).all()
        teeth = tuple(
            ToothSnapshot(
                tooth_number=row.tooth_number,
                dentition=row.tooth_type or "permanent",
                present=(row.general_condition or "healthy") not in MISSING_TOOTH_CONDITIONS,
                is_displaced=bool(row.is_displaced),
                is_rotated=bool(row.is_rotated),
            )
            for row in rows
        )
        return DentitionSnapshot(teeth=teeth)

    # --- assessments ------------------------------------------------------------

    async def create_assessment(
        self, *, clinic_id: UUID, patient_id: UUID, created_by: UUID, payload
    ) -> OrthoAssessment:
        dentition = await self._load_dentition(clinic_id, patient_id)
        measurements = {
            "skeletal_pattern": payload.skeletal_pattern,
            "growth_stage": payload.growth_stage,
            "overjet_mm": payload.overjet_mm,
            "overbite_mm": payload.overbite_mm,
            "crowding_upper_mm": payload.crowding_upper_mm,
            "crowding_lower_mm": payload.crowding_lower_mm,
            "molar_relation_left": payload.molar_relation_left,
            "molar_relation_right": payload.molar_relation_right,
            "canine_relation_left": payload.canine_relation_left,
            "canine_relation_right": payload.canine_relation_right,
        }
        sufficiency = build_sufficiency(
            measurements=measurements,
            dentition=dentition,
        )
        assessment = OrthoAssessment(
            clinic_id=clinic_id,
            patient_id=patient_id,
            created_by=created_by,
            dentition_snapshot={
                "teeth": [
                    {
                        "tooth_number": t.tooth_number,
                        "dentition": t.dentition,
                        "present": t.present,
                        "is_displaced": t.is_displaced,
                        "is_rotated": t.is_rotated,
                    }
                    for t in dentition.teeth
                ]
            },
            data_sufficiency=sufficiency,
            **measurements,
            posterior_crossbite=payload.posterior_crossbite,
            objectives=list(payload.objectives),
            notes=payload.notes,
        )
        self._db.add(assessment)
        await self._db.commit()
        await self._db.refresh(assessment)
        return assessment

    async def get_assessment(self, clinic_id: UUID, assessment_id: UUID) -> OrthoAssessment | None:
        stmt = select(OrthoAssessment).where(
            OrthoAssessment.id == assessment_id,
            OrthoAssessment.clinic_id == clinic_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_assessments(self, clinic_id: UUID, patient_id: UUID) -> list[OrthoAssessment]:
        stmt = (
            select(OrthoAssessment)
            .where(
                OrthoAssessment.clinic_id == clinic_id,
                OrthoAssessment.patient_id == patient_id,
            )
            .order_by(OrthoAssessment.created_at.desc())
        )
        return list((await self._db.execute(stmt)).scalars().all())

    # --- plan generation ------------------------------------------------------------

    def _case_from_assessment(
        self, assessment: OrthoAssessment, dentition: DentitionSnapshot
    ) -> PlannerCase:
        measurements = {
            "skeletal_pattern": assessment.skeletal_pattern,
            "growth_stage": assessment.growth_stage,
            "overjet_mm": assessment.overjet_mm,
            "overbite_mm": assessment.overbite_mm,
            "crowding_upper_mm": assessment.crowding_upper_mm,
            "crowding_lower_mm": assessment.crowding_lower_mm,
            "molar_relation_left": assessment.molar_relation_left,
            "molar_relation_right": assessment.molar_relation_right,
            "canine_relation_left": assessment.canine_relation_left,
            "canine_relation_right": assessment.canine_relation_right,
        }
        sufficiency = build_sufficiency(
            measurements=measurements or {},
            dentition=dentition,
        )
        return PlannerCase(
            patient_id=assessment.patient_id,
            skeletal_pattern=assessment.skeletal_pattern,
            growth_stage=assessment.growth_stage,
            overjet_mm=assessment.overjet_mm,
            overbite_mm=assessment.overbite_mm,
            crowding_upper_mm=assessment.crowding_upper_mm,
            crowding_lower_mm=assessment.crowding_lower_mm,
            molar_relation_left=assessment.molar_relation_left,
            molar_relation_right=assessment.molar_relation_right,
            canine_relation_left=assessment.canine_relation_left,
            canine_relation_right=assessment.canine_relation_right,
            posterior_crossbite=bool(assessment.posterior_crossbite),
            objectives=tuple(assessment.objectives or ()),
            dentition=dentition,
            sufficiency=sufficiency,
        )

    async def generate_proposal(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        assessment_id: UUID,
        created_by: UUID,
        provider: PlanningProvider | None = None,
    ) -> OrthoPlanProposal:
        assessment = await self.get_assessment(clinic_id, assessment_id)
        if assessment is None or assessment.patient_id != patient_id:
            raise KeyError("Assessment not found")

        case = self._case_from_assessment(
            assessment, await self._load_dentition(clinic_id, patient_id)
        )

        resolved = provider or get_provider()
        try:
            suggestion = resolved.propose_plan(case)
        except InsufficientDataError:
            raise
        except Exception as exc:  # provider crash — fail closed, not stored
            raise ProviderFailureError(str(exc)) from exc

        # Independent deterministic gate — outside the provider, always.
        report = evaluate_stages(case, tuple(suggestion.stages))
        if not report.is_valid:
            await event_bus.publish(
                EventType.ORTHO_PLAN_REFUSED,
                {
                    "clinic_id": str(clinic_id),
                    "patient_id": str(patient_id),
                    "assessment_id": str(assessment_id),
                    "provider": suggestion.provider,
                    "provider_version": suggestion.provider_version,
                    "hard_violations": [v.code for v in report.hard],
                },
            )
            raise PlanningRefusedError(report)

        proposal = OrthoPlanProposal(
            clinic_id=clinic_id,
            patient_id=patient_id,
            assessment_id=assessment_id,
            created_by=created_by,
            provider=suggestion.provider,
            provider_version=suggestion.provider_version,
            constraints_version=CONSTRAINTS_VERSION,
            status=STATUS_DRAFT,
            stage_count=len(suggestion.stages),
            planned_months=max(
                1, math.ceil(len(suggestion.stages) * STAGE_INTERVAL_WEEKS / WEEKS_PER_MONTH)
            ),
            score=suggestion.score,
            confidence=suggestion.confidence,
            rationale=suggestion.rationale,
            stages={"stages": [stage.as_dict() for stage in suggestion.stages]},
            constraint_report=report.as_dict(),
            uncertainty=list(suggestion.uncertainty),
        )
        self._db.add(proposal)
        await self._db.commit()
        await self._db.refresh(proposal)

        await event_bus.publish(
            EventType.ORTHO_PROPOSAL_CREATED,
            {
                "proposal_id": str(proposal.id),
                "assessment_id": str(assessment_id),
                "patient_id": str(patient_id),
                "clinic_id": str(clinic_id),
                "provider": suggestion.provider,
                "status": STATUS_DRAFT,
                "stage_count": len(suggestion.stages),
            },
        )
        return proposal

    # --- proposals --------------------------------------------------------------------

    async def get_proposal(self, clinic_id: UUID, proposal_id: UUID) -> OrthoPlanProposal | None:
        stmt = (
            select(OrthoPlanProposal)
            .options(selectinload(OrthoPlanProposal.assessment))
            .where(
                OrthoPlanProposal.id == proposal_id,
                OrthoPlanProposal.clinic_id == clinic_id,
            )
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_proposals(self, clinic_id: UUID, patient_id: UUID) -> list[OrthoPlanProposal]:
        stmt = (
            select(OrthoPlanProposal)
            .where(
                OrthoPlanProposal.clinic_id == clinic_id,
                OrthoPlanProposal.patient_id == patient_id,
            )
            .order_by(OrthoPlanProposal.created_at.desc())
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def review_proposal(
        self,
        *,
        clinic_id: UUID,
        proposal_id: UUID,
        reviewed_by: UUID,
        decision: str,
        note: str | None,
    ) -> OrthoPlanProposal:
        proposal = await self.get_proposal(clinic_id, proposal_id)
        if proposal is None:
            raise KeyError("Proposal not found")
        if proposal.status != STATUS_DRAFT:
            raise ValueError(
                f"Proposal already reviewed (status '{proposal.status}'); "
                "only draft proposals can be approved or rejected"
            )
        proposal.status = decision
        proposal.reviewed_by = reviewed_by
        proposal.reviewed_at = datetime.now(UTC)
        proposal.review_note = note
        await self._db.commit()
        await self._db.refresh(proposal)

        await event_bus.publish(
            EventType.ORTHO_PROPOSAL_REVIEWED,
            {
                "proposal_id": str(proposal.id),
                "patient_id": str(proposal.patient_id),
                "clinic_id": str(clinic_id),
                "decision": decision,
                "reviewed_by": str(reviewed_by),
                "reviewed_at": proposal.reviewed_at.isoformat(),
            },
        )
        return proposal

    async def delete_proposal(self, clinic_id: UUID, proposal_id: UUID) -> None:
        proposal = await self.get_proposal(clinic_id, proposal_id)
        if proposal is None:
            raise KeyError("Proposal not found")
        await self._db.delete(proposal)
        await self._db.commit()
