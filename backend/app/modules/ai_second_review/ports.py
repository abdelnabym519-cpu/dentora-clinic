"""Ports used by the AI Second Review application service."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.ai_treatment_planning.models import AITreatmentPlanningRecord
from app.modules.treatment_simulation.models import TreatmentSimulationRecord

from .models import AISecondReviewRecord


class SecondReviewRepositoryPort(Protocol):
    async def reserve_next_version(self, *, clinic_id: UUID, patient_id: UUID) -> int | None: ...

    async def save(self, row: AISecondReviewRecord) -> AISecondReviewRecord: ...

    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> AISecondReviewRecord | None: ...

    async def get_history(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> list[AISecondReviewRecord]: ...

    async def get_for_review(
        self, *, clinic_id: UUID, review_id: UUID
    ) -> AISecondReviewRecord | None: ...

    async def commit(self, row: AISecondReviewRecord) -> AISecondReviewRecord: ...


class ReviewedArtifactReaderPort(Protocol):
    async def get_simulation(
        self, *, clinic_id: UUID, patient_id: UUID, simulation_id: UUID
    ) -> TreatmentSimulationRecord | None: ...

    async def get_planning(
        self, *, clinic_id: UUID, patient_id: UUID, planning_id: UUID
    ) -> AITreatmentPlanningRecord | None: ...


class SecondReviewGeneratorPort(Protocol):
    async def __call__(self, **kwargs): ...
