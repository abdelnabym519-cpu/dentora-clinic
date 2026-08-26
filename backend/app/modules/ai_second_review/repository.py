"""SQLAlchemy adapters for AI Second Review persistence and artifact reads."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_treatment_planning.models import AITreatmentPlanningRecord
from app.modules.patients.models import Patient
from app.modules.treatment_simulation.models import TreatmentSimulationRecord

from .models import AISecondReviewRecord


class SqlAlchemySecondReviewRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def reserve_next_version(self, *, clinic_id: UUID, patient_id: UUID) -> int | None:
        patient = await self.db.scalar(
            select(Patient)
            .where(
                Patient.id == patient_id,
                Patient.clinic_id == clinic_id,
                Patient.status != "archived",
            )
            .with_for_update()
        )
        if patient is None:
            return None
        latest = await self.get_latest(clinic_id=clinic_id, patient_id=patient_id)
        return 1 if latest is None else latest.review_version + 1

    async def save(self, row: AISecondReviewRecord) -> AISecondReviewRecord:
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> AISecondReviewRecord | None:
        return await self.db.scalar(
            select(AISecondReviewRecord)
            .where(
                AISecondReviewRecord.clinic_id == clinic_id,
                AISecondReviewRecord.patient_id == patient_id,
            )
            .order_by(desc(AISecondReviewRecord.review_version))
            .limit(1)
        )

    async def get_history(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> list[AISecondReviewRecord]:
        return list(
            (
                await self.db.scalars(
                    select(AISecondReviewRecord)
                    .where(
                        AISecondReviewRecord.clinic_id == clinic_id,
                        AISecondReviewRecord.patient_id == patient_id,
                    )
                    .order_by(AISecondReviewRecord.review_version)
                )
            ).all()
        )

    async def get_for_review(
        self, *, clinic_id: UUID, review_id: UUID
    ) -> AISecondReviewRecord | None:
        return await self.db.scalar(
            select(AISecondReviewRecord).where(
                AISecondReviewRecord.id == review_id,
                AISecondReviewRecord.clinic_id == clinic_id,
            )
        )

    async def commit(self, row: AISecondReviewRecord) -> AISecondReviewRecord:
        await self.db.commit()
        await self.db.refresh(row)
        return row


class SqlAlchemyReviewedArtifactReader:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_simulation(
        self, *, clinic_id: UUID, patient_id: UUID, simulation_id: UUID
    ) -> TreatmentSimulationRecord | None:
        return await self.db.scalar(
            select(TreatmentSimulationRecord).where(
                TreatmentSimulationRecord.id == simulation_id,
                TreatmentSimulationRecord.clinic_id == clinic_id,
                TreatmentSimulationRecord.patient_id == patient_id,
            )
        )

    async def get_planning(
        self, *, clinic_id: UUID, patient_id: UUID, planning_id: UUID
    ) -> AITreatmentPlanningRecord | None:
        return await self.db.scalar(
            select(AITreatmentPlanningRecord).where(
                AITreatmentPlanningRecord.id == planning_id,
                AITreatmentPlanningRecord.clinic_id == clinic_id,
                AITreatmentPlanningRecord.patient_id == patient_id,
            )
        )
