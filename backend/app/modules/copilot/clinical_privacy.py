"""Structured privacy projection for Clinical Copilot LLM input."""

from __future__ import annotations

from typing import Any

from app.core.agents.redaction import Redactor

from .clinical_contracts import CLINICAL_COPILOT_INPUT_VERSION


def build_clinical_copilot_input(
    *,
    snapshot: Any,
    risk_evaluation: Any,
    planning: Any,
    simulation: Any,
    focus: str,
    second_review_gate_digest: str,
) -> tuple[dict[str, Any], str]:
    """Build identifier-free input from already structured/reviewed contracts only."""

    from app.modules.ai_treatment_planning.privacy import build_planning_llm_input
    from app.modules.case_intelligence.contracts import digest_value

    planning_input, _ = build_planning_llm_input(snapshot, risk_evaluation)
    case = planning_input["case"]
    risk_context = planning_input["risk_context"]

    limitations = [
        {
            "section": name,
            "status": section["status"],
            "reason": section.get("reason"),
        }
        for name, section in sorted(case["sections"].items())
        if section["status"] in {"not_available", "invalid_or_stale"}
    ]

    payload = {
        "input_contract_version": CLINICAL_COPILOT_INPUT_VERSION,
        "focus": focus,
        "case": case,
        "risk_context": risk_context,
        "reviewed_planning": {
            "planning_version": planning.planning_version,
            "review_status": planning.review_status.value,
            "clinical_output": planning.clinical_output,
            "options": [option.model_dump(mode="json") for option in planning.content.options],
            "data_gaps": [gap.model_dump(mode="json") for gap in planning.content.data_gaps],
        },
        "reviewed_simulation": {
            "simulation_version": simulation.simulation_version,
            "option_id": simulation.provenance.option_id,
            "checkpoints": [
                {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "sequence": checkpoint.sequence,
                    "kind": checkpoint.kind,
                    "label": checkpoint.label,
                    "purpose": checkpoint.purpose,
                    "evidence_ids": checkpoint.evidence_ids,
                    "risk_factor_ids": checkpoint.risk_factor_ids,
                    "predicted_outcome": checkpoint.predicted_outcome,
                }
                for checkpoint in simulation.scene.checkpoints
            ],
            "risk_map_status": simulation.scene.risk_map.status,
            "predicts_biological_outcome": simulation.predicts_biological_outcome,
        },
        "second_review": {
            "status": "passed",
            "gate_digest": second_review_gate_digest,
            "checks": [
                "current_case_matches_reviewed_plan",
                "current_risk_matches_reviewed_plan",
                "simulation_matches_reviewed_plan",
                "simulation_matches_current_case_and_risk",
            ],
        },
        "required_limitations": limitations,
        "guardrails": {
            "advisory_only": True,
            "dentist_review_required": True,
            "no_autonomous_diagnosis": True,
            "no_autonomous_treatment_decision": True,
            "no_canonical_record_mutation": True,
            "structured_input_only": True,
            "free_text_clinical_notes_excluded": True,
        },
    }
    redacted = Redactor(enabled=True).redact_result(payload)
    return redacted, digest_value(redacted)


__all__ = ["build_clinical_copilot_input"]
