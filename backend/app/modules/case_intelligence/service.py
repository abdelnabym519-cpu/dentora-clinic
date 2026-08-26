"""Case Intelligence application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.events.types import EventType
from app.modules.dental_3d.change_detection import (
    ChangeDetectionResponse,
    build_change_detection_response,
)
from app.modules.patients.models import Patient

from .aggregation import CaseAggregator
from .contracts import CaseSnapshot
from .models import CaseSnapshotRecord
from .ports import CaseSourceProvider
from .source_provider import SqlAlchemyCaseSourceProvider


class CaseIntelligenceService:
    """Build/reuse append-only unified case snapshots from authoritative sources."""

    provider: CaseSourceProvider = SqlAlchemyCaseSourceProvider()

    @classmethod
    async def get_current(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
    ) -> CaseSnapshot:
        # Serialize concurrent materialization for the same patient without mutating
        # canonical records. Source modules remain authoritative and read-only here.
        locked_patient = await db.scalar(
            select(Patient)
            .where(
                Patient.id == patient_id,
                Patient.clinic_id == clinic_id,
                Patient.status != "archived",
            )
            .with_for_update()
        )
        if locked_patient is None:
            raise KeyError("patient_not_found")

        sections = await cls.provider.collect(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        aggregated = CaseAggregator.aggregate(
            clinic_id=clinic_id,
            patient_id=patient_id,
            sections=sections,
        )
        latest = await db.scalar(
            select(CaseSnapshotRecord)
            .where(
                CaseSnapshotRecord.clinic_id == clinic_id,
                CaseSnapshotRecord.patient_id == patient_id,
            )
            .order_by(desc(CaseSnapshotRecord.snapshot_version))
            .limit(1)
        )
        if latest is not None and latest.source_digest == aggregated.source_digest:
            return cls._to_contract(latest)

        version = 1 if latest is None else latest.snapshot_version + 1
        generated_at = datetime.now(UTC)
        payload = aggregated.model_dump(mode="json")
        row = CaseSnapshotRecord(
            clinic_id=clinic_id,
            patient_id=patient_id,
            snapshot_version=version,
            contract_version=aggregated.contract_version,
            source_digest=aggregated.source_digest,
            snapshot_data=payload,
            source_versions=aggregated.source_versions,
            generated_at=generated_at,
            generated_by=user_id,
        )
        db.add(row)
        await db.commit()
        await event_bus.publish(
            EventType.CASE_INTELLIGENCE_SNAPSHOT_CREATED,
            {
                "clinic_id": str(clinic_id),
                "patient_id": str(patient_id),
                "snapshot_id": str(row.id),
                "snapshot_version": version,
                "contract_version": aggregated.contract_version,
                "source_digest": aggregated.source_digest,
            },
        )
        return cls._to_contract(row)

    @classmethod
    async def get_version(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        version: int,
    ) -> CaseSnapshot:
        row = await db.scalar(
            select(CaseSnapshotRecord).where(
                CaseSnapshotRecord.clinic_id == clinic_id,
                CaseSnapshotRecord.patient_id == patient_id,
                CaseSnapshotRecord.snapshot_version == version,
            )
        )
        if row is None:
            raise KeyError("snapshot_not_found")
        return cls._to_contract(row)

    @classmethod
    async def compare_versions(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        baseline_version: int,
        followup_version: int,
    ) -> ChangeDetectionResponse:
        """Compare immutable versions while Case Intelligence owns all persistence reads."""

        if followup_version <= baseline_version:
            raise ValueError("followup_version must be greater than baseline_version")

        baseline = await cls.get_version(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            version=baseline_version,
        )
        followup = await cls.get_version(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            version=followup_version,
        )
        return build_change_detection_response(
            patient_id=patient_id,
            baseline_version=baseline_version,
            followup_version=followup_version,
            baseline_payload=baseline.model_dump(mode="json"),
            followup_payload=followup.model_dump(mode="json"),
            baseline_source_digest=baseline.source_digest,
            followup_source_digest=followup.source_digest,
            baseline_source_versions=dict(baseline.source_versions),
            followup_source_versions=dict(followup.source_versions),
        )

    @staticmethod
    def _to_contract(row: CaseSnapshotRecord) -> CaseSnapshot:
        payload = dict(row.snapshot_data)
        return CaseSnapshot.model_validate(
            {
                **payload,
                "case_snapshot_version": row.snapshot_version,
                "generated_at": row.generated_at,
                "source_digest": row.source_digest,
                "source_versions": row.source_versions,
            }
        )
