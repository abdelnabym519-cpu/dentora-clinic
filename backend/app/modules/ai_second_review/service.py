"""AI Second Review application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.base import Provider
from app.core.llm.factory import get_provider
from app.modules.ai_treatment_planning.contracts import ReviewStatus
from app.modules.ai_treatment_planning.service import AITreatmentPlanningService
from app.modules.case_intelligence.contracts import digest_value
from app.modules.case_intelligence.service import CaseIntelligenceService
from app.modules.risk_engine.contracts import RISK_ENGINE_VERSION, RISK_POLICY_VERSION
from app.modules.risk_engine.engine import evaluate_snapshot
from app.modules.treatment_simulation.contracts import (
    TREATMENT_SIMULATION_CONTRACT_VERSION,
    TREATMENT_SIMULATION_ENGINE_VERSION,
)
from app.modules.treatment_simulation.service import TreatmentSimulationService
from app.modules.treatment_simulation.simulator import (
    SimulationBuildError,
    build_digital_twin_scene,
)

from .contracts import (
    AI_SECOND_REVIEW_CONTRACT_VERSION,
    AI_SECOND_REVIEW_INPUT_VERSION,
    AI_SECOND_REVIEW_PROMPT_VERSION,
    PROVIDER_CONTRACT_VERSION,
    AISecondReviewResult,
    ModelProvenance,
    SecondReviewChainReference,
    SecondReviewContent,
    SecondReviewStatus,
)
from .generator import SecondReviewGenerationError, generate_second_review
from .models import AISecondReviewRecord
from .ports import (
    ReviewedArtifactReaderPort,
    SecondReviewGeneratorPort,
    SecondReviewRepositoryPort,
)
from .privacy import build_second_review_llm_input
from .repository import SqlAlchemyReviewedArtifactReader, SqlAlchemySecondReviewRepository


class SecondReviewSafetyError(ValueError):
    """Raised when the reviewed artifact chain cannot be proven current and coherent."""


class AISecondReviewService:
    provider_factory = staticmethod(get_provider)
    generator: SecondReviewGeneratorPort = staticmethod(generate_second_review)

    @classmethod
    async def generate(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        simulation_id: UUID,
        user_id: UUID | None,
        provider_name: str | None = None,
        model: str | None = None,
        provider: Provider | None = None,
        repository: SecondReviewRepositoryPort | None = None,
        artifact_reader: ReviewedArtifactReaderPort | None = None,
    ) -> AISecondReviewResult:
        repository = repository or SqlAlchemySecondReviewRepository(db)
        artifact_reader = artifact_reader or SqlAlchemyReviewedArtifactReader(db)

        simulation_row = await artifact_reader.get_simulation(
            clinic_id=clinic_id,
            patient_id=patient_id,
            simulation_id=simulation_id,
        )
        if simulation_row is None:
            raise KeyError("simulation_not_found")
        planning_row = await artifact_reader.get_planning(
            clinic_id=clinic_id,
            patient_id=patient_id,
            planning_id=simulation_row.planning_id,
        )
        if planning_row is None:
            raise KeyError("planning_not_found")

        snapshot = await CaseIntelligenceService.get_current(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
        )
        risk_evaluation = evaluate_snapshot(snapshot)
        planning = AITreatmentPlanningService._to_contract(planning_row)
        simulation = TreatmentSimulationService._to_contract(simulation_row)
        cls._assert_reviewable_chain(
            planning_row=planning_row,
            simulation_row=simulation_row,
            snapshot=snapshot,
            risk_evaluation=risk_evaluation,
            planning=planning,
            simulation=simulation,
        )

        llm_input, input_digest = build_second_review_llm_input(
            snapshot,
            risk_evaluation,
            planning,
            simulation,
        )
        provider_name = provider_name or settings.COPILOT_PROVIDER_DEFAULT
        if model is None:
            if provider_name != "openai":
                raise SecondReviewGenerationError("no_default_model_for_provider")
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

        version = await repository.reserve_next_version(
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        if version is None:
            raise KeyError("patient_not_found")

        row = AISecondReviewRecord(
            clinic_id=clinic_id,
            patient_id=patient_id,
            review_version=version,
            contract_version=AI_SECOND_REVIEW_CONTRACT_VERSION,
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            case_source_digest=snapshot.source_digest,
            risk_engine_version=RISK_ENGINE_VERSION,
            risk_policy_version=RISK_POLICY_VERSION,
            risk_input_digest=risk_evaluation.input_digest,
            risk_result_digest=risk_evaluation.result_digest,
            planning_id=planning.id,
            planning_version=planning.planning_version,
            planning_output_digest=planning.provenance.output_digest,
            planning_reviewed_at=planning.reviewed_at,
            planning_reviewed_by=planning.reviewed_by,
            option_id=simulation.provenance.option_id,
            simulation_id=simulation.id,
            simulation_version=simulation.simulation_version,
            simulation_engine_version=simulation.provenance.simulation_engine_version,
            simulation_input_digest=simulation.provenance.input_digest,
            simulation_output_digest=simulation.provenance.output_digest,
            provider_name=provider_name,
            model_name=model,
            provider_contract_version=PROVIDER_CONTRACT_VERSION,
            prompt_version=AI_SECOND_REVIEW_PROMPT_VERSION,
            input_contract_version=AI_SECOND_REVIEW_INPUT_VERSION,
            input_digest=input_digest,
            output_digest=output_digest,
            review_data=output_payload,
            review_status=SecondReviewStatus.PENDING_REVIEW.value,
            generated_at=datetime.now(UTC),
            generated_by=user_id,
        )
        return cls._to_contract(await repository.save(row))

    @staticmethod
    def _assert_reviewable_chain(
        *, planning_row, simulation_row, snapshot, risk_evaluation, planning, simulation
    ) -> None:
        if planning_row.review_status != ReviewStatus.ACCEPTED.value:
            raise SecondReviewSafetyError("accepted_treatment_planning_required")
        if planning_row.reviewed_at is None or planning_row.reviewed_by is None:
            raise SecondReviewSafetyError("accepted_planning_missing_review_provenance")

        link_checks = (
            (simulation_row.planning_id, planning_row.id),
            (simulation_row.planning_version, planning_row.planning_version),
            (simulation_row.planning_output_digest, planning_row.output_digest),
            (simulation_row.planning_reviewed_at, planning_row.reviewed_at),
            (simulation_row.planning_reviewed_by, planning_row.reviewed_by),
        )
        if any(actual != expected for actual, expected in link_checks):
            raise SecondReviewSafetyError("simulation_planning_provenance_mismatch")

        current_checks = (
            (snapshot.source_digest, planning_row.case_source_digest),
            (snapshot.case_snapshot_version, planning_row.case_snapshot_version),
            (snapshot.contract_version, planning_row.case_snapshot_contract_version),
            (RISK_ENGINE_VERSION, planning_row.risk_engine_version),
            (RISK_POLICY_VERSION, planning_row.risk_policy_version),
            (risk_evaluation.input_digest, planning_row.risk_input_digest),
            (risk_evaluation.result_digest, planning_row.risk_result_digest),
            (snapshot.source_digest, simulation_row.case_source_digest),
            (snapshot.case_snapshot_version, simulation_row.case_snapshot_version),
            (snapshot.contract_version, simulation_row.case_snapshot_contract_version),
            (RISK_ENGINE_VERSION, simulation_row.risk_engine_version),
            (RISK_POLICY_VERSION, simulation_row.risk_policy_version),
            (risk_evaluation.input_digest, simulation_row.risk_input_digest),
            (risk_evaluation.result_digest, simulation_row.risk_result_digest),
            (TREATMENT_SIMULATION_CONTRACT_VERSION, simulation_row.contract_version),
            (TREATMENT_SIMULATION_ENGINE_VERSION, simulation_row.engine_version),
        )
        if any(current != reviewed for current, reviewed in current_checks):
            raise SecondReviewSafetyError("second_review_artifact_chain_is_stale")

        expected_input_digest = digest_value(
            {
                "contract_version": TREATMENT_SIMULATION_CONTRACT_VERSION,
                "engine_version": TREATMENT_SIMULATION_ENGINE_VERSION,
                "patient_id": str(snapshot.identity.patient_id),
                "planning_id": str(planning.id),
                "planning_version": planning.planning_version,
                "planning_output_digest": planning.provenance.output_digest,
                "planning_review_status": planning.review_status.value,
                "planning_reviewed_at": planning.reviewed_at,
                "planning_reviewed_by": str(planning.reviewed_by),
                "option_id": simulation.provenance.option_id,
                "case_snapshot_version": snapshot.case_snapshot_version,
                "case_source_digest": snapshot.source_digest,
                "risk_input_digest": risk_evaluation.input_digest,
                "risk_result_digest": risk_evaluation.result_digest,
                "reference_frame": snapshot.reference_frame.model_dump(mode="json"),
            }
        )
        if expected_input_digest != simulation.provenance.input_digest:
            raise SecondReviewSafetyError("simulation_input_digest_mismatch")

        try:
            expected_scene = build_digital_twin_scene(
                snapshot=snapshot,
                risk_evaluation=risk_evaluation,
                planning=planning,
                option_id=simulation.provenance.option_id,
            )
        except SimulationBuildError as exc:
            raise SecondReviewSafetyError(str(exc)) from exc
        expected_payload = expected_scene.model_dump(mode="json")
        if simulation.scene != expected_scene:
            raise SecondReviewSafetyError("simulation_scene_no_longer_matches_reviewed_inputs")
        if digest_value(expected_payload) != simulation.provenance.output_digest:
            raise SecondReviewSafetyError("simulation_output_digest_mismatch")

    @classmethod
    async def get_latest(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        repository: SecondReviewRepositoryPort | None = None,
    ) -> AISecondReviewResult:
        repository = repository or SqlAlchemySecondReviewRepository(db)
        row = await repository.get_latest(clinic_id=clinic_id, patient_id=patient_id)
        if row is None:
            raise KeyError("second_review_not_found")
        return cls._to_contract(row)

    @classmethod
    async def get_history(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        repository: SecondReviewRepositoryPort | None = None,
    ) -> list[AISecondReviewResult]:
        repository = repository or SqlAlchemySecondReviewRepository(db)
        rows = await repository.get_history(clinic_id=clinic_id, patient_id=patient_id)
        return [cls._to_contract(row) for row in rows]

    @classmethod
    async def mark_reviewed(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        review_id: UUID,
        reviewer_id: UUID,
        reviewer_role: str,
        repository: SecondReviewRepositoryPort | None = None,
    ) -> AISecondReviewResult:
        if reviewer_role != "dentist":
            raise PermissionError("dentist_review_required")
        repository = repository or SqlAlchemySecondReviewRepository(db)
        row = await repository.get_for_review(clinic_id=clinic_id, review_id=review_id)
        if row is None:
            raise KeyError("second_review_not_found")
        if row.review_status != SecondReviewStatus.PENDING_REVIEW.value:
            raise ValueError("second_review_already_reviewed")
        row.review_status = SecondReviewStatus.REVIEWED.value
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        return cls._to_contract(await repository.commit(row))

    @staticmethod
    def _to_contract(row: AISecondReviewRecord) -> AISecondReviewResult:
        return AISecondReviewResult(
            id=row.id,
            patient_id=row.patient_id,
            review_version=row.review_version,
            contract_version=row.contract_version,
            chain_reference=SecondReviewChainReference(
                case_snapshot_version=row.case_snapshot_version,
                case_snapshot_contract_version=row.case_snapshot_contract_version,
                case_source_digest=row.case_source_digest,
                risk_engine_version=row.risk_engine_version,
                risk_policy_version=row.risk_policy_version,
                risk_input_digest=row.risk_input_digest,
                risk_result_digest=row.risk_result_digest,
                planning_id=row.planning_id,
                planning_version=row.planning_version,
                planning_output_digest=row.planning_output_digest,
                planning_reviewed_at=row.planning_reviewed_at,
                planning_reviewed_by=row.planning_reviewed_by,
                option_id=row.option_id,
                simulation_id=row.simulation_id,
                simulation_version=row.simulation_version,
                simulation_engine_version=row.simulation_engine_version,
                simulation_input_digest=row.simulation_input_digest,
                simulation_output_digest=row.simulation_output_digest,
            ),
            content=SecondReviewContent.model_validate(row.review_data),
            provenance=ModelProvenance(
                provider=row.provider_name,
                model=row.model_name,
                provider_contract_version=row.provider_contract_version,
                prompt_version=row.prompt_version,
                input_contract_version=row.input_contract_version,
                input_digest=row.input_digest,
                output_digest=row.output_digest,
            ),
            review_status=SecondReviewStatus(row.review_status),
            clinical_output=row.review_status == SecondReviewStatus.REVIEWED.value,
            generated_at=row.generated_at,
            generated_by=row.generated_by,
            reviewed_at=row.reviewed_at,
            reviewed_by=row.reviewed_by,
        )


__all__ = ["AISecondReviewService", "SecondReviewSafetyError"]
