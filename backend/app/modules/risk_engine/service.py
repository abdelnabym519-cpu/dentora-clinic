"""Risk Engine application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.case_intelligence.service import CaseIntelligenceService
from app.modules.patients.models import Patient

from .contracts import (
    RISK_ENGINE_VERSION,
    RISK_POLICY_VERSION,
    RISK_RESULT_CONTRACT_VERSION,
    ReviewStatus,
    RiskProvenance,
    RiskResult,
)
from .engine import evaluate_snapshot
from .models import RiskResultRecord


class RiskEngineService:
    @classmethod
    async def generate(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
    ) -> RiskResult:
        snapshot = await CaseIntelligenceService.get_current(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
        )
        evaluation = evaluate_snapshot(snapshot)

        # Serialize append-only version assignment without mutating the patient.
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
        latest = await db.scalar(
            select(RiskResultRecord)
            .where(
                RiskResultRecord.clinic_id == clinic_id,
                RiskResultRecord.patient_id == patient_id,
            )
            .order_by(desc(RiskResultRecord.result_version))
            .limit(1)
        )
        version = 1 if latest is None else latest.result_version + 1
        generated_at = datetime.now(UTC)
        result_data = {
            "factors": [item.model_dump(mode="json") for item in evaluation.factors],
            "evidence": [item.model_dump(mode="json") for item in evaluation.evidence],
            "risk_map": evaluation.risk_map.model_dump(mode="json"),
        }
        row = RiskResultRecord(
            clinic_id=clinic_id,
            patient_id=patient_id,
            result_version=version,
            contract_version=RISK_RESULT_CONTRACT_VERSION,
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            source_digest=snapshot.source_digest,
            input_digest=evaluation.input_digest,
            result_digest=evaluation.result_digest,
            engine_version=RISK_ENGINE_VERSION,
            policy_version=RISK_POLICY_VERSION,
            availability_state=evaluation.availability_state,
            result_data=result_data,
            review_status=ReviewStatus.PENDING_REVIEW.value,
            generated_at=generated_at,
            generated_by=user_id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return cls._to_contract(row)

    @classmethod
    async def get_latest(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> RiskResult:
        row = await db.scalar(
            select(RiskResultRecord)
            .where(
                RiskResultRecord.clinic_id == clinic_id,
                RiskResultRecord.patient_id == patient_id,
            )
            .order_by(desc(RiskResultRecord.result_version))
            .limit(1)
        )
        if row is None:
            raise KeyError("risk_result_not_found")
        return cls._to_contract(row)

    @classmethod
    async def get_history(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> list[RiskResult]:
        rows = (
            await db.scalars(
                select(RiskResultRecord)
                .where(
                    RiskResultRecord.clinic_id == clinic_id,
                    RiskResultRecord.patient_id == patient_id,
                )
                .order_by(RiskResultRecord.result_version)
            )
        ).all()
        return [cls._to_contract(row) for row in rows]

    @classmethod
    async def review(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        result_id: UUID,
        reviewer_id: UUID,
        reviewer_role: str,
        decision: str,
    ) -> RiskResult:
        if reviewer_role != "dentist":
            raise PermissionError("dentist_review_required")
        row = await db.scalar(
            select(RiskResultRecord)
            .where(
                RiskResultRecord.id == result_id,
                RiskResultRecord.clinic_id == clinic_id,
            )
            .with_for_update()
        )
        if row is None:
            raise KeyError("risk_result_not_found")
        if row.review_status != ReviewStatus.PENDING_REVIEW.value:
            raise ValueError("risk_result_already_reviewed")
        if decision not in {ReviewStatus.ACCEPTED.value, ReviewStatus.REJECTED.value}:
            raise ValueError("invalid_review_decision")
        row.review_status = decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(row)
        return cls._to_contract(row)

    @staticmethod
    def _to_contract(row: RiskResultRecord) -> RiskResult:
        payload = dict(row.result_data)
        return RiskResult.model_validate(
            {
                "id": row.id,
                "patient_id": row.patient_id,
                "result_version": row.result_version,
                "contract_version": row.contract_version,
                "factors": payload.get("factors", []),
                "evidence": payload.get("evidence", []),
                "risk_map": payload.get("risk_map", {"status": "unavailable"}),
                "provenance": RiskProvenance(
                    case_snapshot_version=row.case_snapshot_version,
                    case_snapshot_contract_version=row.case_snapshot_contract_version,
                    source_digest=row.source_digest,
                    input_digest=row.input_digest,
                    result_digest=row.result_digest,
                    engine_version=row.engine_version,
                    policy_version=row.policy_version,
                    generated_at=row.generated_at,
                    availability_state=row.availability_state,
                ),
                "review_status": ReviewStatus(row.review_status),
                "generated_by": row.generated_by,
                "reviewed_at": row.reviewed_at,
                "reviewed_by": row.reviewed_by,
            }
        )


__all__ = ["RiskEngineService"]
