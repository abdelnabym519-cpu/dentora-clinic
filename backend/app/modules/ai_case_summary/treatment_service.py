"""AI Treatment Planning application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.base import Provider
from app.core.llm.factory import get_provider
from app.modules.case_intelligence.contracts import digest_value
from app.modules.case_intelligence.service import CaseIntelligenceService
from app.modules.patients.models import Patient
from app.modules.risk_engine.contracts import ReviewStatus as RiskReviewStatus
from app.modules.risk_engine.service import RiskEngineService

from .contracts import ReviewStatus as SummaryReviewStatus
from .privacy import build_redacted_llm_input
from .service import PROVIDER_CONTRACT_VERSION, AICaseSummaryService
from .treatment_contracts import (
    AI_TREATMENT_PLAN_CONTRACT_VERSION,
    AI_TREATMENT_PLAN_PROMPT_VERSION,
    AITreatmentPlan,
    TreatmentModelProvenance,
    TreatmentPlanContent,
    TreatmentPlanningInputs,
    TreatmentReviewStatus,
)
from .treatment_generator import TreatmentGenerationError, generate_treatment_plan
from .treatment_models import AITreatmentPlanRecord


class AITreatmentPlanningService:
    """Generate append-only drafts without writing canonical treatment-plan state."""

    provider_factory = staticmethod(get_provider)

    @classmethod
    async def generate(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        provider_name: str | None = None,
        model: str | None = None,
        provider: Provider | None = None,
    ) -> AITreatmentPlan:
        snapshot = await CaseIntelligenceService.get_current(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
        )
        summary = await AICaseSummaryService.get_latest(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        if summary.review_status != SummaryReviewStatus.ACCEPTED:
            raise TreatmentGenerationError("accepted_case_summary_required")
        if summary.unified_case.case_source_digest != snapshot.source_digest:
            raise TreatmentGenerationError("accepted_case_summary_is_stale")

        risk = await RiskEngineService.get_latest(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        if risk.review_status != RiskReviewStatus.ACCEPTED:
            raise TreatmentGenerationError("accepted_risk_result_required")
        if risk.provenance.source_digest != snapshot.source_digest:
            raise TreatmentGenerationError("accepted_risk_result_is_stale")

        llm_input, _ = build_redacted_llm_input(snapshot)
        llm_input["accepted_case_summary"] = {
            "summary_version": summary.summary_version,
            "claims": [claim.model_dump(mode="json") for claim in summary.content.claims],
            "data_gaps": [gap.model_dump(mode="json") for gap in summary.content.data_gaps],
        }
        llm_input["accepted_risk_result"] = {
            "result_version": risk.result_version,
            "factors": [factor.model_dump(mode="json") for factor in risk.factors],
            "risk_map": risk.risk_map.model_dump(mode="json"),
            "availability_state": risk.provenance.availability_state,
        }
        input_digest = digest_value(llm_input)

        provider_name = provider_name or settings.COPILOT_PROVIDER_DEFAULT
        if model is None:
            if provider_name != "openai":
                raise TreatmentGenerationError("no_default_model_for_provider")
            model = settings.COPILOT_MODEL_CHAT_OPENAI
        provider = provider or cls.provider_factory(provider_name)
        generated = await generate_treatment_plan(
            provider=provider,
            model=model,
            llm_input=llm_input,
            max_tokens=settings.COPILOT_MAX_TOKENS,
        )
        output_payload = generated.content.model_dump(mode="json")
        output_digest = digest_value(output_payload)

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
            select(AITreatmentPlanRecord)
            .where(
                AITreatmentPlanRecord.clinic_id == clinic_id,
                AITreatmentPlanRecord.patient_id == patient_id,
            )
            .order_by(desc(AITreatmentPlanRecord.plan_version))
            .limit(1)
        )
        version = 1 if latest is None else latest.plan_version + 1
        row = AITreatmentPlanRecord(
            clinic_id=clinic_id,
            patient_id=patient_id,
            plan_version=version,
            contract_version=AI_TREATMENT_PLAN_CONTRACT_VERSION,
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            case_source_digest=snapshot.source_digest,
            summary_id=summary.id,
            summary_version=summary.summary_version,
            summary_output_digest=summary.provenance.output_digest,
            risk_result_id=risk.id,
            risk_result_version=risk.result_version,
            risk_result_digest=risk.provenance.result_digest,
            provider_name=provider_name,
            model_name=model,
            provider_contract_version=PROVIDER_CONTRACT_VERSION,
            prompt_version=AI_TREATMENT_PLAN_PROMPT_VERSION,
            input_digest=input_digest,
            output_digest=output_digest,
            plan_data=output_payload,
            review_status=TreatmentReviewStatus.PENDING_REVIEW.value,
            generated_at=datetime.now(UTC),
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
    ) -> AITreatmentPlan:
        row = await db.scalar(
            select(AITreatmentPlanRecord)
            .where(
                AITreatmentPlanRecord.clinic_id == clinic_id,
                AITreatmentPlanRecord.patient_id == patient_id,
            )
            .order_by(desc(AITreatmentPlanRecord.plan_version))
            .limit(1)
        )
        if row is None:
            raise KeyError("treatment_plan_not_found")
        return cls._to_contract(row)

    @classmethod
    async def get_history(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> list[AITreatmentPlan]:
        rows = (
            await db.scalars(
                select(AITreatmentPlanRecord)
                .where(
                    AITreatmentPlanRecord.clinic_id == clinic_id,
                    AITreatmentPlanRecord.patient_id == patient_id,
                )
                .order_by(AITreatmentPlanRecord.plan_version)
            )
        ).all()
        return [cls._to_contract(row) for row in rows]

    @classmethod
    async def review(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        plan_id: UUID,
        reviewer_id: UUID,
        reviewer_role: str,
        decision: str,
    ) -> AITreatmentPlan:
        if reviewer_role != "dentist":
            raise PermissionError("dentist_review_required")
        row = await db.scalar(
            select(AITreatmentPlanRecord)
            .where(
                AITreatmentPlanRecord.id == plan_id,
                AITreatmentPlanRecord.clinic_id == clinic_id,
            )
            .with_for_update()
        )
        if row is None:
            raise KeyError("treatment_plan_not_found")
        if row.review_status != TreatmentReviewStatus.PENDING_REVIEW.value:
            raise ValueError("treatment_plan_already_reviewed")
        if decision not in {
            TreatmentReviewStatus.ACCEPTED.value,
            TreatmentReviewStatus.REJECTED.value,
        }:
            raise ValueError("invalid_review_decision")
        row.review_status = decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(row)
        return cls._to_contract(row)

    @staticmethod
    def _to_contract(row: AITreatmentPlanRecord) -> AITreatmentPlan:
        return AITreatmentPlan(
            id=row.id,
            patient_id=row.patient_id,
            plan_version=row.plan_version,
            contract_version=row.contract_version,
            inputs=TreatmentPlanningInputs(
                case_snapshot_version=row.case_snapshot_version,
                case_snapshot_contract_version=row.case_snapshot_contract_version,
                case_source_digest=row.case_source_digest,
                summary_id=row.summary_id,
                summary_version=row.summary_version,
                summary_output_digest=row.summary_output_digest,
                risk_result_id=row.risk_result_id,
                risk_result_version=row.risk_result_version,
                risk_result_digest=row.risk_result_digest,
            ),
            content=TreatmentPlanContent.model_validate(row.plan_data),
            provenance=TreatmentModelProvenance(
                provider=row.provider_name,
                model=row.model_name,
                provider_contract_version=row.provider_contract_version,
                prompt_version=row.prompt_version,
                input_digest=row.input_digest,
                output_digest=row.output_digest,
            ),
            review_status=TreatmentReviewStatus(row.review_status),
            clinical_output=row.review_status == TreatmentReviewStatus.ACCEPTED.value,
            generated_at=row.generated_at,
            generated_by=row.generated_by,
            reviewed_at=row.reviewed_at,
            reviewed_by=row.reviewed_by,
        )


__all__ = ["AITreatmentPlanningService"]
