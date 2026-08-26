from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.clinical_copilot.contracts import (
    ClinicalCopilotContext,
    ClinicalStageStatus,
    StageName,
    StageState,
)
from app.modules.clinical_copilot.guarded import _enforce_cross_stage_readiness


def test_risk_failure_marks_every_downstream_stage_stale() -> None:
    now = datetime.now(UTC)
    context = ClinicalCopilotContext(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        stages=[
            ClinicalStageStatus(
                stage=StageName.CASE_INTELLIGENCE,
                state=StageState.READY,
                generated_at=now,
            ),
            ClinicalStageStatus(
                stage=StageName.RISK_ENGINE,
                state=StageState.UNAVAILABLE,
                generated_at=now,
                reason="risk_context_unavailable",
            ),
            ClinicalStageStatus(
                stage=StageName.TREATMENT_PLANNING,
                state=StageState.READY,
                generated_at=now,
            ),
            ClinicalStageStatus(
                stage=StageName.TREATMENT_SIMULATION,
                state=StageState.READY,
                generated_at=now,
            ),
            ClinicalStageStatus(
                stage=StageName.AI_SECOND_REVIEW,
                state=StageState.READY,
                generated_at=now,
            ),
        ],
        evidence_catalog={},
        input_digest="sha256:pre-guard",
        ready_for_advice=True,
    )

    guarded = _enforce_cross_stage_readiness(context)
    by_stage = {stage.stage: stage for stage in guarded.stages}

    assert by_stage[StageName.TREATMENT_PLANNING].state is StageState.STALE
    assert (
        by_stage[StageName.TREATMENT_PLANNING].reason
        == "treatment_planning_risk_not_ready"
    )
    assert by_stage[StageName.TREATMENT_SIMULATION].state is StageState.STALE
    assert (
        by_stage[StageName.TREATMENT_SIMULATION].reason
        == "treatment_simulation_planning_not_ready"
    )
    assert by_stage[StageName.AI_SECOND_REVIEW].state is StageState.STALE
    assert (
        by_stage[StageName.AI_SECOND_REVIEW].reason
        == "ai_second_review_simulation_not_ready"
    )
    assert guarded.ready_for_advice is False
