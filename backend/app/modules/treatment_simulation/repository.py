"""SQLAlchemy adapters for Treatment Simulation persistence and plan reads."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_treatment_planning.models import AITreatmentPlanningRecord
from app.modules.patients.models import Patient

from .models import TreatmentSimulationRecord


class SqlAlchemySimulationRepository:
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
        return 1 if latest is None else latest.simulation_version + 1

    async def get_by_input_digest(
        self, *, clinic_id: UUID, patient_id: UUID, input_digest: str
    ) -> TreatmentSimulationRecord | None:
        return await self.db.scalar(
            select(TreatmentSimulationRecord)
            .where(
                TreatmentSimulationRecord.clinic_id == clinic_id,
                TreatmentSimulationRecord.patient_id == patient_id,
                TreatmentSimulationRecord.input_digest == input_digest,
            )
            .order_by(desc(TreatmentSimulationRecord.simulation_version))
            .limit(1)
        )

    async def save(self, row: TreatmentSimulationRecord) -> TreatmentSimulationRecord:
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> TreatmentSimulationRecord | None:
        return await self.db.scalar(
            select(TreatmentSimulationRecord)
            .where(
                TreatmentSimulationRecord.clinic_id == clinic_id,
                TreatmentSimulationRecord.patient_id == patient_id,
            )
            .order_by(desc(TreatmentSimulationRecord.simulation_version))
            .limit(1)
        )

    async def get_history(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> list[TreatmentSimulationRecord]:
        return list(
            (
                await self.db.scalars(
                    select(TreatmentSimulationRecord)
                    .where(
                        TreatmentSimulationRecord.clinic_id == clinic_id,
                        TreatmentSimulationRecord.patient_id == patient_id,
                    )
                    .order_by(TreatmentSimulationRecord.simulation_version)
                )
            ).all()
        )


class SqlAlchemyPlanningArtifactReader:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, *, clinic_id: UUID, patient_id: UUID, planning_id: UUID
    ) -> AITreatmentPlanningRecord | None:
        return await self.db.scalar(
            select(AITreatmentPlanningRecord).where(
                AITreatmentPlanningRecord.id == planning_id,
                AITreatmentPlanningRecord.clinic_id == clinic_id,
                AITreatmentPlanningRecord.patient_id == patient_id,
            )
        )
