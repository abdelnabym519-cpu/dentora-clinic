"""Ports used by the Treatment Simulation application service."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.ai_treatment_planning.models import AITreatmentPlanningRecord

from .models import TreatmentSimulationRecord


class SimulationRepositoryPort(Protocol):
    async def reserve_next_version(self, *, clinic_id: UUID, patient_id: UUID) -> int | None: ...

    async def get_by_input_digest(
        self, *, clinic_id: UUID, patient_id: UUID, input_digest: str
    ) -> TreatmentSimulationRecord | None: ...

    async def save(self, row: TreatmentSimulationRecord) -> TreatmentSimulationRecord: ...

    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> TreatmentSimulationRecord | None: ...

    async def get_history(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> list[TreatmentSimulationRecord]: ...


class PlanningArtifactReaderPort(Protocol):
    async def get(
        self, *, clinic_id: UUID, patient_id: UUID, planning_id: UUID
    ) -> AITreatmentPlanningRecord | None: ...
