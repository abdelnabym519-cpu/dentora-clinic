"""Clinical Copilot application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.base import Provider
from app.core.llm.factory import get_provider

from .clinical_contracts import (
    CLINICAL_COPILOT_PROMPT_VERSION,
    CLINICAL_COPILOT_SECOND_REVIEW_GATE_VERSION,
    PROVIDER_CONTRACT_VERSION,
    ClinicalCopilotModelProvenance,
    ClinicalCopilotResult,
    ClinicalCopilotWorkflowReference,
)
from .clinical_generator import ClinicalCopilotGenerationError, generate_clinical_copilot
from .clinical_privacy import build_clinical_copilot_input


class ClinicalCopilotUnavailable(RuntimeError):
    """Fail-closed workflow state; detail contains only non-PHI machine reasons."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


class ClinicalCopilotService:
    provider_factory = staticmethod(get_provider)
    generator = staticmethod(generate_clinical_copilot)

    @staticmethod
    def _second_review_gate(*, snapshot, risk_evaluation, planning, simulation) -> str:
        from app.modules.ai_treatment_planning.contracts import ReviewStatus
        from app.modules.case_intelligence.contracts import digest_value
        from app.modules.risk_engine.contracts import RISK_ENGINE_VERSION, RISK_POLICY_VERSION

        reasons: list[str] = []

        if (
            planning.review_status is not ReviewStatus.ACCEPTED
            or not planning.clinical_output
            or planning.reviewed_at is None
            or planning.reviewed_by is None
        ):
            reasons.append("dentist_accepted_planning_required")

        case_ref = planning.case_reference
        if (
            case_ref.case_snapshot_version != snapshot.case_snapshot_version
            or case_ref.case_snapshot_contract_version != snapshot.contract_version
            or case_ref.case_source_digest != snapshot.source_digest
        ):
            reasons.append("accepted_planning_case_evidence_is_stale")
        if (
            case_ref.risk_engine_version != RISK_ENGINE_VERSION
            or case_ref.risk_policy_version != RISK_POLICY_VERSION
            or case_ref.risk_input_digest != risk_evaluation.input_digest
            or case_ref.risk_result_digest != risk_evaluation.result_digest
        ):
            reasons.append("accepted_planning_risk_evidence_is_stale")

        sim = simulation.provenance
        if (
            sim.planning_id != planning.id
            or sim.planning_version != planning.planning_version
            or sim.planning_output_digest != planning.provenance.output_digest
            or sim.planning_reviewed_at != planning.reviewed_at
            or sim.planning_reviewed_by != planning.reviewed_by
        ):
            reasons.append("simulation_does_not_match_reviewed_planning")
        if (
            sim.case_snapshot_version != snapshot.case_snapshot_version
            or sim.case_snapshot_contract_version != snapshot.contract_version
            or sim.case_source_digest != snapshot.source_digest
            or sim.risk_engine_version != RISK_ENGINE_VERSION
            or sim.risk_policy_version != RISK_POLICY_VERSION
            or sim.risk_input_digest != risk_evaluation.input_digest
            or sim.risk_result_digest != risk_evaluation.result_digest
        ):
            reasons.append("simulation_evidence_is_stale")

        stale_sections = sorted(
            name
            for name, status in snapshot.availability.items()
            if status.value == "invalid_or_stale"
        )
        if stale_sections:
            reasons.append("case_contains_invalid_or_stale_data")

        if reasons:
            raise ClinicalCopilotUnavailable(*reasons)

        return digest_value(
            {
                "gate_version": CLINICAL_COPILOT_SECOND_REVIEW_GATE_VERSION,
                "case_snapshot_version": snapshot.case_snapshot_version,
                "case_source_digest": snapshot.source_digest,
                "risk_input_digest": risk_evaluation.input_digest,
                "risk_result_digest": risk_evaluation.result_digest,
                "planning_id": str(planning.id),
                "planning_version": planning.planning_version,
                "planning_output_digest": planning.provenance.output_digest,
                "planning_reviewed_at": planning.reviewed_at,
                "planning_reviewed_by": str(planning.reviewed_by),
                "simulation_id": str(simulation.id),
                "simulation_version": simulation.simulation_version,
                "simulation_input_digest": simulation.provenance.input_digest,
                "simulation_output_digest": simulation.provenance.output_digest,
            }
        )

    @classmethod
    async def generate(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        user_role: str,
        focus: str,
        provider_name: str | None = None,
        model: str | None = None,
        provider: Provider | None = None,
    ) -> ClinicalCopilotResult:
        if user_role != "dentist":
            raise PermissionError("dentist_control_required")

        from app.modules.ai_treatment_planning.service import AITreatmentPlanningService
        from app.modules.case_intelligence.contracts import digest_value
        from app.modules.case_intelligence.service import CaseIntelligenceService
        from app.modules.risk_engine.contracts import RISK_ENGINE_VERSION, RISK_POLICY_VERSION
        from app.modules.risk_engine.engine import evaluate_snapshot
        from app.modules.treatment_simulation.service import TreatmentSimulationService

        snapshot = await CaseIntelligenceService.get_current(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
        )
        risk_evaluation = evaluate_snapshot(snapshot)
        try:
            planning = await AITreatmentPlanningService.get_latest(
                db,
                clinic_id=clinic_id,
                patient_id=patient_id,
            )
            simulation = await TreatmentSimulationService.get_latest(
                db,
                clinic_id=clinic_id,
                patient_id=patient_id,
            )
        except KeyError as exc:
            raise ClinicalCopilotUnavailable("reviewed_workflow_context_incomplete") from exc

        gate_digest = cls._second_review_gate(
            snapshot=snapshot,
            risk_evaluation=risk_evaluation,
            planning=planning,
            simulation=simulation,
        )
        llm_input, input_digest = build_clinical_copilot_input(
            snapshot=snapshot,
            risk_evaluation=risk_evaluation,
            planning=planning,
            simulation=simulation,
            focus=focus,
            second_review_gate_digest=gate_digest,
        )

        provider_name = provider_name or settings.COPILOT_PROVIDER_DEFAULT
        if model is None:
            if provider_name != "openai":
                raise ClinicalCopilotGenerationError("no_default_model_for_provider")
            model = settings.COPILOT_MODEL_CHAT_OPENAI
        provider = provider or cls.provider_factory(provider_name)
        generated = await cls.generator(
            provider=provider,
            model=model,
            llm_input=llm_input,
            max_tokens=settings.COPILOT_MAX_TOKENS,
        )
        output_digest = digest_value(generated.content.model_dump(mode="json"))

        return ClinicalCopilotResult(
            patient_id=patient_id,
            focus=focus,
            content=generated.content,
            workflow=ClinicalCopilotWorkflowReference(
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
                simulation_id=simulation.id,
                simulation_version=simulation.simulation_version,
                simulation_input_digest=simulation.provenance.input_digest,
                simulation_output_digest=simulation.provenance.output_digest,
                simulation_option_id=simulation.provenance.option_id,
                second_review_gate_digest=gate_digest,
            ),
            provenance=ClinicalCopilotModelProvenance(
                provider=provider_name,
                model=model,
                provider_contract_version=PROVIDER_CONTRACT_VERSION,
                prompt_version=CLINICAL_COPILOT_PROMPT_VERSION,
                input_digest=input_digest,
                output_digest=output_digest,
            ),
            generated_at=datetime.now(UTC),
            generated_by=user_id,
        )


__all__ = ["ClinicalCopilotService", "ClinicalCopilotUnavailable"]
