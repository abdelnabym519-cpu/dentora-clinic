"""Pure deterministic Treatment Simulation scene builder."""

from __future__ import annotations

from app.modules.ai_treatment_planning.contracts import AITreatmentPlanningResult
from app.modules.case_intelligence.contracts import AvailabilityStatus, CaseSnapshot
from app.modules.risk_engine.engine import RiskEvaluation

from .contracts import DigitalTwinScene, SimulationCheckpoint

_DIGITAL_TWIN_SECTIONS = (
    "anatomy",
    "nerve",
    "alignment",
    "cbct",
    "ios",
    "prosthetic",
    "odontogram",
    "periodontogram",
    "implant_planning",
)


class SimulationBuildError(ValueError):
    """Raised when reviewed evidence cannot safely produce a viewer scene."""


def build_digital_twin_scene(
    *,
    snapshot: CaseSnapshot,
    risk_evaluation: RiskEvaluation,
    planning: AITreatmentPlanningResult,
    option_id: str,
) -> DigitalTwinScene:
    """Build a staged viewer scene without predicting or mutating geometry."""

    if planning.review_status.value != "accepted" or not planning.clinical_output:
        raise SimulationBuildError("accepted_treatment_planning_required")
    if planning.reviewed_at is None or planning.reviewed_by is None:
        raise SimulationBuildError("accepted_planning_missing_review_provenance")
    if snapshot.reference_frame.status != AvailabilityStatus.AVAILABLE:
        raise SimulationBuildError("accepted_patient_space_reference_frame_required")
    reference_frame = snapshot.reference_frame.data
    if not isinstance(reference_frame, dict) or not reference_frame:
        raise SimulationBuildError("accepted_patient_space_reference_frame_required")

    selected = next(
        (item for item in planning.content.options if item.option_id == option_id), None
    )
    if selected is None:
        raise SimulationBuildError("planning_option_not_found")

    checkpoints = [
        SimulationCheckpoint(
            checkpoint_id="baseline",
            sequence=0,
            kind="baseline",
            label="Current accepted patient-space evidence",
        )
    ]
    for sequence, step in enumerate(selected.steps, start=1):
        checkpoints.append(
            SimulationCheckpoint(
                checkpoint_id=f"step:{step.step_id}",
                sequence=sequence,
                kind="planned_step",
                label=step.description,
                purpose=step.purpose,
                source_step_id=step.step_id,
                evidence_ids=sorted(set(step.evidence_ids)),
                risk_factor_ids=sorted(set(step.risk_factor_ids)),
            )
        )

    source_sections = [
        name
        for name in _DIGITAL_TWIN_SECTIONS
        if snapshot.clinical_state[name].status == AvailabilityStatus.AVAILABLE
    ]
    return DigitalTwinScene(
        reference_frame=reference_frame,
        source_sections=source_sections,
        risk_map=risk_evaluation.risk_map,
        checkpoints=checkpoints,
        selected_checkpoint_id="baseline",
    )


__all__ = ["SimulationBuildError", "build_digital_twin_scene"]
