"""Privacy boundary for AI Second Review LLM input."""

from __future__ import annotations

from typing import Any

from app.core.agents.redaction import Redactor
from app.modules.ai_treatment_planning.contracts import AITreatmentPlanningResult
from app.modules.ai_treatment_planning.privacy import build_planning_llm_input
from app.modules.case_intelligence.contracts import CaseSnapshot, digest_value
from app.modules.risk_engine.engine import RiskEvaluation
from app.modules.treatment_simulation.contracts import TreatmentSimulationResult

from .contracts import AI_SECOND_REVIEW_INPUT_VERSION


def _remove_patient_space_identifiers(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_patient_space_identifiers(item)
            for key, item in value.items()
            if not key.lower().endswith("_uid")
        }
    if isinstance(value, list):
        return [_remove_patient_space_identifiers(item) for item in value]
    return value


def _planning_refs(planning: AITreatmentPlanningResult, option_id: str) -> list[str]:
    selected = next(
        (option for option in planning.content.options if option.option_id == option_id),
        None,
    )
    if selected is None:
        return []
    return [f"option:{selected.option_id}"] + [f"step:{step.step_id}" for step in selected.steps]


def _planning_payload(planning: AITreatmentPlanningResult, option_id: str) -> dict[str, Any]:
    selected = next(
        (option for option in planning.content.options if option.option_id == option_id),
        None,
    )
    if selected is None:
        raise ValueError("planning_option_not_found")
    return {
        "contract_version": planning.contract_version,
        "planning_version": planning.planning_version,
        "output_digest": planning.provenance.output_digest,
        "review_status": planning.review_status.value,
        "dentist_reviewed": planning.reviewed_at is not None and planning.reviewed_by is not None,
        "selected_option": selected.model_dump(mode="json"),
        "allowed_refs": _planning_refs(planning, option_id),
    }


def _simulation_payload(simulation: TreatmentSimulationResult) -> dict[str, Any]:
    scene = simulation.scene
    return {
        "contract_version": simulation.contract_version,
        "simulation_version": simulation.simulation_version,
        "engine_version": simulation.provenance.simulation_engine_version,
        "input_digest": simulation.provenance.input_digest,
        "output_digest": simulation.provenance.output_digest,
        "option_id": simulation.provenance.option_id,
        "scene": {
            "contract_version": scene.contract_version,
            "renderer": scene.renderer,
            "coordinate_space": scene.coordinate_space,
            "source_sections": scene.source_sections,
            "risk_map": scene.risk_map.model_dump(mode="json"),
            "checkpoints": [item.model_dump(mode="json") for item in scene.checkpoints],
            "selected_checkpoint_id": scene.selected_checkpoint_id,
            "synthetic_geometry": scene.synthetic_geometry,
            "mutates_source_geometry": scene.mutates_source_geometry,
        },
        "allowed_refs": [item.checkpoint_id for item in scene.checkpoints],
    }


def build_second_review_llm_input(
    snapshot: CaseSnapshot,
    risk_evaluation: RiskEvaluation,
    planning: AITreatmentPlanningResult,
    simulation: TreatmentSimulationResult,
) -> tuple[dict[str, Any], str]:
    """Build a structured/redacted chain without patient identifiers or raw free-text notes."""

    planning_projection, _ = build_planning_llm_input(snapshot, risk_evaluation)
    payload = {
        "input_contract_version": AI_SECOND_REVIEW_INPUT_VERSION,
        "case": _remove_patient_space_identifiers(planning_projection["case"]),
        "risk_context": _remove_patient_space_identifiers(planning_projection["risk_context"]),
        "planning": _planning_payload(planning, simulation.provenance.option_id),
        "simulation": _simulation_payload(simulation),
        "guardrails": {
            "advisory_only": True,
            "dentist_review_required": True,
            "no_treatment_approval": True,
            "no_canonical_record_mutation": True,
            "no_new_diagnosis": True,
            "no_predicted_biological_outcome": True,
        },
    }
    redacted = Redactor(enabled=True).redact_result(payload)
    return redacted, digest_value(redacted)


__all__ = ["build_second_review_llm_input"]
