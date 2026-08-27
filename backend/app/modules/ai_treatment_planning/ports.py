"""Application ports for AI Treatment Planning."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.core.llm.base import Provider

from .generator import GenerationResult
from .models import AITreatmentPlanningRecord


class PlanningGeneratorPort(Protocol):
    async def __call__(
        self,
        *,
        provider: Provider,
        model: str,
        llm_input: dict,
        max_tokens: int,
    ) -> GenerationResult: ...


class PlanningRepositoryPort(Protocol):
    async def reserve_next_version(self, *, clinic_id: UUID, patient_id: UUID) -> int | None: ...

    async def save(self, row: AITreatmentPlanningRecord) -> AITreatmentPlanningRecord: ...

    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> AITreatmentPlanningRecord | None: ...

    async def get_history(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> list[AITreatmentPlanningRecord]: ...

    async def get_for_review(
        self, *, clinic_id: UUID, planning_id: UUID
    ) -> AITreatmentPlanningRecord | None: ...

    async def commit(self, row: AITreatmentPlanningRecord) -> AITreatmentPlanningRecord: ...
