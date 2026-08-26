"""Ports owned by Clinical Copilot.

The AI Second Review adapter is intentionally injected: Clinical Copilot must not invent
review facts when that upstream stage is not installed in the current repository state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class SecondReviewArtifact:
    artifact_id: str
    version: int
    generated_at: datetime
    source_digest: str
    simulation_id: str
    simulation_output_digest: str
    review_status: str
    reviewed_at: datetime | None
    reviewed_by: UUID | None
    evidence_refs: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


class SecondReviewReader(Protocol):
    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> SecondReviewArtifact | None: ...


class UnavailableSecondReviewReader:
    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> SecondReviewArtifact | None:
        return None
