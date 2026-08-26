"""AI Treatment Planning application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.base import Provider
from app.core.llm.factory import get_provider
from app.modules.case_intelligence.contracts import digest_value
from app.modules.case_intelligence.service import CaseIntelligenceService
from app.modules.risk_engine.contracts import RISK_ENGINE_VERSION, RISK_POLICY_VERSION
from app.modules.risk_engine.engine import evaluate_snapshot

from .contracts import (
    AI_TREATMENT_PLANNING_CONTRACT_VERSION,
    AI_TREATMENT_PLANNING_INPUT_VERSION,
    AI_TREATMENT_PLANNING_PROMPT_VERSION,
    PROVIDER_CONTRACT_VERSION,
    AITreatmentPlanningResult,
    ModelProvenance,
    PlanningCaseReference,
    PlanningContent,
    ReviewStatus,
)
from .generator import PlanningGenerationError, generate_planning_options
from .models import AITreatmentPlanningRecord
from .ports import PlanningGeneratorPort, PlanningRepositoryPort
from .privacy import build_planning_llm_input
from .repository import SqlAlchemyPlanningRepository


class AITreatmentPlanningService:
    provider_factory = staticmethod(get_provider)
    generator: PlanningGeneratorPort = staticmethod(generate_planning_options)

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
        repository: PlanningRepositoryPort | None = None,
    ) -> AITreatmentPlanningResult:
        snapshot = await CaseIntelligenceService.get_current(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
        )
        risk_evaluation = evaluate_snapshot(snapshot)
        llm_input, input_digest = build_planning_llm_input(snapshot, risk_evaluation)

        provider_name = provider_name or settings.COPILOT_PROVIDER_DEFAULT
        if model is None:
            if provider_name != "openai":
                raise PlanningGenerationError("no_default_model_for_provider")
            model = settings.COPILOT_MODEL_CHAT_OPENAI
        provider = provider or cls.provider_factory(provider_name)
        generated = await cls.generator(
            provider=provider,
            model=model,
            llm_input=llm_input,
            max_tokens=settings.COPILOT_MAX_TOKENS,
        )
        output_payload = generated.content.model_dump(mode="json")
        output_digest = digest_value(output_payload)

        repository = repository or SqlAlchemyPlanningRepository(db)
        version = await repository.reserve_next_version(
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        if version is None:
            raise KeyError("patient_not_found")

        row = AITreatmentPlanningRecord(
            clinic_id=clinic_id,
            patient_id=patient_id,
            planning_version=version,
            contract_version=AI_TREATMENT_PLANNING_CONTRACT_VERSION,
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            case_source_digest=snapshot.source_digest,
            risk_engine_version=RISK_ENGINE_VERSION,
            risk_policy_version=RISK_POLICY_VERSION,
            risk_input_digest=risk_evaluation.input_digest,
            risk_result_digest=risk_evaluation.result_digest,
            risk_availability_state=risk_evaluation.availability_state,
            provider_name=provider_name,
            model_name=model,
            provider_contract_version=PROVIDER_CONTRACT_VERSION,
            prompt_version=AI_TREATMENT_PLANNING_PROMPT_VERSION,
            input_contract_version=AI_TREATMENT_PLANNING_INPUT_VERSION,
            input_digest=input_digest,
            output_digest=output_digest,
            planning_data=output_payload,
            review_status=ReviewStatus.PENDING_REVIEW.value,
            generated_at=datetime.now(UTC),
            generated_by=user_id,
        )
        return cls._to_contract(await repository.save(row))

    @classmethod
    async def get_latest(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        repository: PlanningRepositoryPort | None = None,
    ) -> AITreatmentPlanningResult:
        repository = repository or SqlAlchemyPlanningRepository(db)
        row = await repository.get_latest(clinic_id=clinic_id, patient_id=patient_id)
        if row is None:
            raise KeyError("planning_not_found")
        return cls._to_contract(row)

    @classmethod
    async def get_history(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        repository: PlanningRepositoryPort | None = None,
    ) -> list[AITreatmentPlanningResult]:
        repository = repository or SqlAlchemyPlanningRepository(db)
        rows = await repository.get_history(clinic_id=clinic_id, patient_id=patient_id)
        return [cls._to_contract(row) for row in rows]

    @classmethod
    async def review(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        planning_id: UUID,
        reviewer_id: UUID,
        reviewer_role: str,
        decision: str,
        repository: PlanningRepositoryPort | None = None,
    ) -> AITreatmentPlanningResult:
        if reviewer_role != "dentist":
            raise PermissionError("dentist_review_required")
        repository = repository or SqlAlchemyPlanningRepository(db)
        row = await repository.get_for_review(clinic_id=clinic_id, planning_id=planning_id)
        if row is None:
            raise KeyError("planning_not_found")
        if row.review_status != ReviewStatus.PENDING_REVIEW.value:
            raise ValueError("planning_already_reviewed")
        if decision not in {ReviewStatus.ACCEPTED.value, ReviewStatus.REJECTED.value}:
            raise ValueError("invalid_review_decision")
        row.review_status = decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        return cls._to_contract(await repository.commit(row))

    @staticmethod
    def _to_contract(row: AITreatmentPlanningRecord) -> AITreatmentPlanningResult:
        return AITreatmentPlanningResult(
            id=row.id,
            patient_id=row.patient_id,
            planning_version=row.planning_version,
            contract_version=row.contract_version,
            case_reference=PlanningCaseReference(
                case_snapshot_version=row.case_snapshot_version,
                case_snapshot_contract_version=row.case_snapshot_contract_version,
                case_source_digest=row.case_source_digest,
                risk_engine_version=row.risk_engine_version,
                risk_policy_version=row.risk_policy_version,
                risk_input_digest=row.risk_input_digest,
                risk_result_digest=row.risk_result_digest,
                risk_availability_state=row.risk_availability_state,
            ),
            content=PlanningContent.model_validate(row.planning_data),
            provenance=ModelProvenance(
                provider=row.provider_name,
                model=row.model_name,
                provider_contract_version=row.provider_contract_version,
                prompt_version=row.prompt_version,
                input_contract_version=row.input_contract_version,
                input_digest=row.input_digest,
                output_digest=row.output_digest,
            ),
            review_status=ReviewStatus(row.review_status),
            clinical_output=row.review_status == ReviewStatus.ACCEPTED.value,
            generated_at=row.generated_at,
            generated_by=row.generated_by,
            reviewed_at=row.reviewed_at,
            reviewed_by=row.reviewed_by,
        )


__all__ = ["AITreatmentPlanningService"]
