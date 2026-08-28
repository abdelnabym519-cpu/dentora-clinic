"""SQLAlchemy composition adapter for authoritative Case Intelligence sources."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .source_clinical import collect_clinical_sources
from .source_dental3d import collect_dental3d_sources
from .source_implant import collect_implant_sources
from .source_records import collect_record_sources


class SqlAlchemyCaseSourceProvider:
    """Read canonical/validated source records; never write to them."""

    async def collect(
        self,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> dict[str, dict[str, Any]]:
        sections = await collect_clinical_sources(db, clinic_id, patient_id)
        sections.update(await collect_record_sources(db, clinic_id, patient_id))
        dental_sections, accepted_alignment_id = await collect_dental3d_sources(
            db, clinic_id, patient_id
        )
        sections.update(dental_sections)
        sections["implant_planning"] = await collect_implant_sources(
            db,
            clinic_id,
            patient_id,
            accepted_alignment_id=accepted_alignment_id,
        )
        return sections
