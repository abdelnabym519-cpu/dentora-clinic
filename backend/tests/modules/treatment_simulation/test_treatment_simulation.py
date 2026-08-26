from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.ai_treatment_planning.contracts import (
    AITreatmentPlanningResult,
    ModelProvenance,
    PlanningCaseReference,
    PlanningContent,
    PlanningStep,
    ReviewStatus,
    TreatmentOption,
)
from app.modules.case_intelligence.contracts import (
    AvailabilityStatus,
    CaseIdentity,
    CaseSection,
    CaseSnapshot,
)
from app.modules.risk_engine.contracts import RiskMap
from app.modules.risk_engine.engine import RiskEvaluation
from app.modules.treatment_simulation.service import TreatmentSimulationService
from app.modules.treatment_simulation.simulator import (
    SimulationBuildError,
    build_digital_twin_scene,
)


def _snapshot() -> CaseSnapshot:
    clinic_id = uuid4()
    patient_id = uuid4()
    sections = {
        name: CaseSection(status=AvailabilityStatus.NOT_AVAILABLE, reason="fixture")
        for name in (
            "patient",
            "anatomy",
            "nerve",
            "alignment",
            "cbct",
            "ios",
            "prosthetic",
            "odontogram",
            "periodontogram",
            "medical_context",
            "treatment_history",
            "timeline",
            "media",
            "implant_planning",
        )
    }
    sections["alignment"] = CaseSection(
        status=AvailabilityStatus.AVAILABLE,
        data={"kind": "dicom_patient", "unit": "mm", "frame_of_reference_uid": "1.2.3"},
    )
    sections["cbct"] = CaseSection(status=AvailabilityStatus.AVAILABLE, data={"studies": []})
    return CaseSnapshot(
        case_snapshot_version=4,
        identity=CaseIdentity(clinic_id=clinic_id, patient_id=patient_id),
        reference_frame=CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={"kind": "dicom_patient", "unit": "mm", "frame_of_reference_uid": "1.2.3"},
        ),
        clinical_state=sections,
        availability={name: section.status for name, section in sections.items()},
        provenance=[],
        missing_data_report=[],
        source_versions={},
        source_digest="sha256:" + "1" * 64,
        generated_at=datetime.now(UTC),
    )


def _planning(snapshot: CaseSnapshot) -> AITreatmentPlanningResult:
    now = datetime.now(UTC)
    return AITreatmentPlanningResult(
        id=uuid4(),
        patient_id=snapshot.identity.patient_id,
        planning_version=2,
        case_reference=PlanningCaseReference(
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            case_source_digest=snapshot.source_digest,
            risk_engine_version="1.0.0",
            risk_policy_version="observed-facts-v1",
            risk_input_digest="sha256:" + "2" * 64,
            risk_result_digest="sha256:" + "3" * 64,
            risk_availability_state="partial",
        ),
        content=PlanningContent(
            options=[
                TreatmentOption(
                    option_id="option-a",
                    title="Reviewed option",
                    clinical_intent="Visualize the reviewed sequence only.",
                    rationale="Grounded in the accepted evidence.",
                    evidence_ids=["E001"],
                    steps=[
                        PlanningStep(
                            step_id="s1",
                            description="First reviewed action",
                            purpose="Show the first reviewed stage",
                            evidence_ids=["E001"],
                            risk_factor_ids=["factor-a"],
                        ),
                        PlanningStep(
                            step_id="s2",
                            description="Second reviewed action",
                            purpose="Show the second reviewed stage",
                            evidence_ids=["E002", "E001"],
                        ),
                    ],
                )
            ]
        ),
        provenance=ModelProvenance(
            provider="fixture",
            model="fixture-model",
            input_digest="sha256:" + "4" * 64,
            output_digest="sha256:" + "5" * 64,
        ),
        review_status=ReviewStatus.ACCEPTED,
        clinical_output=True,
        generated_at=now,
        reviewed_at=now,
        reviewed_by=uuid4(),
    )


def _risk() -> RiskEvaluation:
    return RiskEvaluation(
        factors=[],
        evidence=[],
        risk_map=RiskMap(status="unavailable", reason="fixture_has_no_patient_space_regions"),
        input_digest="sha256:" + "2" * 64,
        result_digest="sha256:" + "3" * 64,
        availability_state="partial",
    )


def test_scene_is_patient_space_deterministic_and_non_predictive() -> None:
    snapshot = _snapshot()
    planning = _planning(snapshot)

    first = build_digital_twin_scene(
        snapshot=snapshot,
        risk_evaluation=_risk(),
        planning=planning,
        option_id="option-a",
    )
    second = build_digital_twin_scene(
        snapshot=snapshot,
        risk_evaluation=_risk(),
        planning=planning,
        option_id="option-a",
    )

    assert first == second
    assert first.renderer == "dental_3d.digital_twin"
    assert first.coordinate_space == "dicom_patient_mm"
    assert first.reference_frame["frame_of_reference_uid"] == "1.2.3"
    assert first.source_sections == ["alignment", "cbct"]
    assert [item.checkpoint_id for item in first.checkpoints] == ["baseline", "step:s1", "step:s2"]
    assert first.checkpoints[2].evidence_ids == ["E001", "E002"]
    assert all(item.geometry_operation == "none" for item in first.checkpoints)
    assert all(item.predicted_outcome is False for item in first.checkpoints)
    assert first.synthetic_geometry is False
    assert first.mutates_source_geometry is False


def test_scene_requires_explicit_reviewed_option_and_patient_space() -> None:
    snapshot = _snapshot()
    planning = _planning(snapshot)

    with pytest.raises(SimulationBuildError, match="planning_option_not_found"):
        build_digital_twin_scene(
            snapshot=snapshot,
            risk_evaluation=_risk(),
            planning=planning,
            option_id="missing",
        )

    snapshot.reference_frame = CaseSection(
        status=AvailabilityStatus.NOT_AVAILABLE,
        reason="no_alignment",
    )
    with pytest.raises(
        SimulationBuildError,
        match="accepted_patient_space_reference_frame_required",
    ):
        build_digital_twin_scene(
            snapshot=snapshot,
            risk_evaluation=_risk(),
            planning=planning,
            option_id="option-a",
        )


def test_stale_reviewed_inputs_are_rejected() -> None:
    snapshot = _snapshot()
    risk = _risk()
    plan_row = SimpleNamespace(
        case_source_digest=snapshot.source_digest,
        case_snapshot_version=snapshot.case_snapshot_version,
        case_snapshot_contract_version=snapshot.contract_version,
        risk_engine_version="1.0.0",
        risk_policy_version="observed-facts-v1",
        risk_input_digest=risk.input_digest,
        risk_result_digest=risk.result_digest,
    )

    TreatmentSimulationService._assert_current_evidence(
        plan_row=plan_row,
        snapshot=snapshot,
        risk_evaluation=risk,
    )

    plan_row.risk_result_digest = "sha256:" + "9" * 64
    with pytest.raises(ValueError, match="accepted_treatment_planning_is_stale"):
        TreatmentSimulationService._assert_current_evidence(
            plan_row=plan_row,
            snapshot=snapshot,
            risk_evaluation=risk,
        )
