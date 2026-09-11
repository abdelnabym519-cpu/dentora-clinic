"""SQL adapter backing the copilot's second-review reader port.

Lives inside ``clinical_copilot`` (next to the ``SecondReviewReader``
protocol in ``ports.py``) so the copilot can consume the persisted AI
Second Review artifact without a reverse dependency on
``ai_clinical_report`` (which composes the copilot). Reads are strictly
read-only against the ``ai_second_review`` persistence contract declared
in this module's manifest ``depends``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_second_review.models import AISecondReviewRecord
from app.modules.clinical_copilot.ports import SecondReviewArtifact, SecondReviewReader


def _evidence_refs(payload: Any) -> list[str]:
    refs: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence_id" and item:
                    refs.add(str(item))
                elif key in {"evidence_ids", "evidence_refs"} and isinstance(item, list):
                    refs.update(str(ref) for ref in item if ref)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return sorted(refs)


class DatabaseSecondReviewReader(SecondReviewReader):
    """Read-only adapter from the existing AI Second Review persistence contract."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_latest(self, *, clinic_id: UUID, patient_id: UUID) -> SecondReviewArtifact | None:
        record = await self.db.scalar(
            select(AISecondReviewRecord)
            .where(
                AISecondReviewRecord.clinic_id == clinic_id,
                AISecondReviewRecord.patient_id == patient_id,
            )
            .order_by(desc(AISecondReviewRecord.review_version))
            .limit(1)
        )
        if record is None:
            return None
        return SecondReviewArtifact(
            artifact_id=str(record.id),
            version=record.review_version,
            generated_at=record.generated_at,
            source_digest=record.output_digest,
            simulation_id=str(record.simulation_id),
            simulation_output_digest=record.simulation_output_digest,
            review_status=record.review_status,
            reviewed_at=record.reviewed_at,
            reviewed_by=record.reviewed_by,
            evidence_refs=_evidence_refs(record.review_data),
            payload=record.review_data,
        )
