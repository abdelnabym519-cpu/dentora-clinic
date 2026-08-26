"""SQLAlchemy adapter for AI Treatment Planning persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.patients.models import Patient

from .models import AITreatmentPlanningRecord


class SqlAlchemyPlanningRepository:
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
        latest = await self.db.scalar(
            select(AITreatmentPlanningRecord)
            .where(
                AITreatmentPlanningRecord.clinic_id == clinic_id,
                AITreatmentPlanningRecord.patient_id == patient_id,
            )
            .order_by(desc(AITreatmentPlanningRecord.planning_version))
            .limit(1)
        )
        return 1 if latest is None else latest.planning_version + 1

    async def save(self, row: AITreatmentPlanningRecord) -> AITreatmentPlanningRecord:
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> AITreatmentPlanningRecord | None:
        return await self.db.scalar(
            select(AITreatmentPlanningRecord)
            .where(
                AITreatmentPlanningRecord.clinic_id == clinic_id,
                AITreatmentPlanningRecord.patient_id == patient_id,
            )
            .order_by(desc(AITreatmentPlanningRecord.planning_version))
            .limit(1)
        )

    async def get_history(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> list[AITreatmentPlanningRecord]:
        return list(
            (
                await self.db.scalars(
                    select(AITreatmentPlanningRecord)
                    .where(
                        AITreatmentPlanningRecord.clinic_id == clinic_id,
                        AITreatmentPlanningRecord.patient_id == patient_id,
                    )
                    .order_by(AITreatmentPlanningRecord.planning_version)
                )
            ).all()
        )

    async def get_for_review(
        self, *, clinic_id: UUID, planning_id: UUID
    ) -> AITreatmentPlanningRecord | None:
        return await self.db.scalar(
            select(AITreatmentPlanningRecord)
            .where(
                AITreatmentPlanningRecord.id == planning_id,
                AITreatmentPlanningRecord.clinic_id == clinic_id,
            )
            .with_for_update()
        )

    async def commit(self, row: AITreatmentPlanningRecord) -> AITreatmentPlanningRecord:
        await self.db.commit()
        await self.db.refresh(row)
        return row
