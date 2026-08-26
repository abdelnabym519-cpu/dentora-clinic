"""Case Intelligence application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.events.types import EventType
from app.modules.patients.models import Patient

from .aggregation import CaseAggregator
from .contracts import CaseSnapshot
from .models import CaseSnapshotRecord
from .ports import CaseSourceProvider
from .source_provider import SqlAlchemyCaseSourceProvider


class CaseIntelligenceService:
    """Build/reuse append-only unified clinical case snapshots from authoritative sources."""

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


class CaseIntelligenceChangeDetectionProvider:
    """Owner-side adapter for the Dental 3D change-detection snapshot port."""

    async def get_snapshot(
        self,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        version: int,
    ):
        from app.modules.dental_3d.change_detection import ChangeDetectionSnapshot

        row = await db.scalar(
            select(CaseSnapshotRecord).where(
                CaseSnapshotRecord.clinic_id == clinic_id,
                CaseSnapshotRecord.patient_id == patient_id,
                CaseSnapshotRecord.snapshot_version == version,
            )
        )
        if row is None:
            raise KeyError("snapshot_not_found")
        return ChangeDetectionSnapshot(
            version=row.snapshot_version,
            payload=dict(row.snapshot_data),
            source_digest=row.source_digest,
            source_versions=dict(row.source_versions or {}),
        )
