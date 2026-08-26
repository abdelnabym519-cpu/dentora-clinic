from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.llm.base import Done, TextDelta
from app.modules.ai_second_review.generator import (
    SecondReviewGenerationError,
    generate_second_review,
)
from app.modules.ai_second_review.privacy import build_second_review_llm_input
from app.modules.ai_second_review.service import AISecondReviewService, SecondReviewSafetyError
from app.modules.ai_treatment_planning.contracts import (
    AITreatmentPlanningResult,
    PlanningCaseReference,
    PlanningContent,
    PlanningStep,
    ReviewStatus,
    TreatmentOption,
)
from app.modules.ai_treatment_planning.contracts import (
    ModelProvenance as PlanningModelProvenance,
)
from app.modules.case_intelligence.contracts import (
    AvailabilityStatus,
    CaseIdentity,
    CaseSection,
    CaseSnapshot,
    digest_value,
)
from app.modules.risk_engine.contracts import RiskMap
from app.modules.risk_engine.engine import RiskEvaluation
from app.modules.treatment_simulation.contracts import (
    TREATMENT_SIMULATION_CONTRACT_VERSION,
    TREATMENT_SIMULATION_ENGINE_VERSION,
    SimulationProvenance,
    TreatmentSimulationResult,
)
from app.modules.treatment_simulation.simulator import build_digital_twin_scene


class _Provider:
    def __init__(self, payload: dict):
        self.payload = payload

    async def complete(self, **kwargs):
        yield TextDelta(json.dumps(self.payload))
        yield Done("stop")


def _llm_input() -> dict:
    return {
        "case": {
            "evidence": {"E001": {"source_module": "fixture"}},
            "sections": {
                "patient": {"status": "available", "reason": None},
                "nerve": {"status": "not_available", "reason": "not provided"},
            },
        },
        "risk_context": {"factors": [{"factor_id": "R001"}]},
        "planning": {"allowed_refs": ["option:O1", "step:S1"]},
        "simulation": {"allowed_refs": ["baseline", "step:S1"]},
    }


@pytest.mark.asyncio
async def test_generator_accepts_only_traceable_findings_and_exact_gaps() -> None:
    payload = {
        "findings": [
            {
                "finding_id": "F1",
                "category": "planning_consistency",
                "statement": "The reviewed step should be checked against the cited evidence.",
                "evidence_ids": ["E001"],
                "risk_factor_ids": ["R001"],
                "planning_refs": ["step:S1"],
                "simulation_refs": ["step:S1"],
            }
        ],
        "data_gaps": [{"section": "nerve", "status": "not_available"}],
    }
    generated = await generate_second_review(
        provider=_Provider(payload),
        model="fixture",
        llm_input=_llm_input(),
        max_tokens=1000,
    )
    assert generated.content.advisory_only is True
    assert generated.content.no_treatment_approval is True
    assert generated.content.findings[0].evidence_ids == ["E001"]
    assert generated.content.data_gaps[0].reason == "not provided"

    payload["findings"][0]["evidence_ids"] = ["UNKNOWN"]
    with pytest.raises(
        SecondReviewGenerationError,
        match="second_review_references_unknown_evidence",
    ):
        await generate_second_review(
            provider=_Provider(payload),
            model="fixture",
            llm_input=_llm_input(),
            max_tokens=1000,
        )


@pytest.mark.asyncio
async def test_generator_rejects_untraceable_finding_and_omitted_gap() -> None:
    payload = {
        "findings": [
            {
                "finding_id": "F1",
                "category": "safety_boundary",
                "statement": "Untraceable statement.",
                "evidence_ids": [],
                "risk_factor_ids": [],
                "planning_refs": [],
                "simulation_refs": [],
            }
        ],
        "data_gaps": [{"section": "nerve", "status": "not_available"}],
    }
    with pytest.raises(
        SecondReviewGenerationError,
        match="second_review_finding_requires_traceable_reference",
    ):
        await generate_second_review(
            provider=_Provider(payload),
            model="fixture",
            llm_input=_llm_input(),
            max_tokens=1000,
        )

    payload["findings"] = []
    payload["data_gaps"] = []
    with pytest.raises(
        SecondReviewGenerationError,
        match="provider_omitted_or_invented_data_gap",
    ):
        await generate_second_review(
            provider=_Provider(payload),
            model="fixture",
            llm_input=_llm_input(),
            max_tokens=1000,
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
    sections["patient"] = CaseSection(
        status=AvailabilityStatus.AVAILABLE,
        data={
            "first_name": "Private",
            "last_name": "Patient",
            "email": "private@example.test",
            "notes": "raw clinical note must never leave",
            "age_years": 42,
        },
    )
    sections["alignment"] = CaseSection(
        status=AvailabilityStatus.AVAILABLE,
        data={
            "kind": "dicom_patient",
            "unit": "mm",
            "frame_of_reference_uid": "1.2.840.privacy-sensitive",
        },
    )
    sections["cbct"] = CaseSection(status=AvailabilityStatus.AVAILABLE, data={"studies": []})
    return CaseSnapshot(
        case_snapshot_version=4,
        identity=CaseIdentity(clinic_id=clinic_id, patient_id=patient_id),
        reference_frame=CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={
                "kind": "dicom_patient",
                "unit": "mm",
                "frame_of_reference_uid": "1.2.840.privacy-sensitive",
            },
        ),
        clinical_state=sections,
        availability={name: section.status for name, section in sections.items()},
        provenance=[],
        missing_data_report=[],
        source_versions={},
        source_digest="sha256:" + "1" * 64,
        generated_at=datetime.now(UTC),
    )


def _risk() -> RiskEvaluation:
    return RiskEvaluation(
        factors=[],
        evidence=[],
        risk_map=RiskMap(status="unavailable", reason="fixture"),
        input_digest="sha256:" + "2" * 64,
        result_digest="sha256:" + "3" * 64,
        availability_state="partial",
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
                    option_id="O1",
                    title="Reviewed option",
                    clinical_intent="Support dentist review.",
                    rationale="Grounded in structured evidence.",
                    evidence_ids=["E001"],
                    steps=[
                        PlanningStep(
                            step_id="S1",
                            description="Reviewed action",
                            purpose="Display only",
                            evidence_ids=["E001"],
                        )
                    ],
                )
            ]
        ),
        provenance=PlanningModelProvenance(
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


def _simulation(
    snapshot: CaseSnapshot,
    planning: AITreatmentPlanningResult,
    risk: RiskEvaluation,
) -> TreatmentSimulationResult:
    scene = build_digital_twin_scene(
        snapshot=snapshot,
        risk_evaluation=risk,
        planning=planning,
        option_id="O1",
    )
    input_digest = digest_value(
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
            "option_id": "O1",
            "case_snapshot_version": snapshot.case_snapshot_version,
            "case_source_digest": snapshot.source_digest,
            "risk_input_digest": risk.input_digest,
            "risk_result_digest": risk.result_digest,
            "reference_frame": snapshot.reference_frame.model_dump(mode="json"),
        }
    )
    now = datetime.now(UTC)
    return TreatmentSimulationResult(
        id=uuid4(),
        patient_id=snapshot.identity.patient_id,
        simulation_version=3,
        scene=scene,
        provenance=SimulationProvenance(
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            case_source_digest=snapshot.source_digest,
            risk_engine_version="1.0.0",
            risk_policy_version="observed-facts-v1",
            risk_input_digest=risk.input_digest,
            risk_result_digest=risk.result_digest,
            planning_id=planning.id,
            planning_version=planning.planning_version,
            planning_output_digest=planning.provenance.output_digest,
            planning_reviewed_at=planning.reviewed_at,
            planning_reviewed_by=planning.reviewed_by,
            option_id="O1",
            input_digest=input_digest,
            output_digest=digest_value(scene.model_dump(mode="json")),
        ),
        generated_at=now,
    )


def test_privacy_projection_excludes_patient_identifiers_notes_and_frame_uid() -> None:
    snapshot = _snapshot()
    risk = _risk()
    planning = _planning(snapshot)
    simulation = _simulation(snapshot, planning, risk)

    payload, input_digest = build_second_review_llm_input(
        snapshot,
        risk,
        planning,
        simulation,
    )
    serialized = json.dumps(payload)
    assert str(snapshot.identity.patient_id) not in serialized
    assert str(snapshot.identity.clinic_id) not in serialized
    assert "Private" not in serialized
    assert "private@example.test" not in serialized
    assert "raw clinical note must never leave" not in serialized
    assert "1.2.840.privacy-sensitive" not in serialized
    assert payload["simulation"]["scene"]["coordinate_space"] == "dicom_patient_mm"
    assert payload["guardrails"]["no_treatment_approval"] is True
    assert input_digest.startswith("sha256:")


def test_chain_validation_rejects_stale_or_modified_simulation() -> None:
    snapshot = _snapshot()
    risk = _risk()
    planning = _planning(snapshot)
    simulation = _simulation(snapshot, planning, risk)
    planning_row = SimpleNamespace(
        id=planning.id,
        planning_version=planning.planning_version,
        output_digest=planning.provenance.output_digest,
        review_status="accepted",
        reviewed_at=planning.reviewed_at,
        reviewed_by=planning.reviewed_by,
        case_source_digest=snapshot.source_digest,
        case_snapshot_version=snapshot.case_snapshot_version,
        case_snapshot_contract_version=snapshot.contract_version,
        risk_engine_version="1.0.0",
        risk_policy_version="observed-facts-v1",
        risk_input_digest=risk.input_digest,
        risk_result_digest=risk.result_digest,
    )
    simulation_row = SimpleNamespace(
        planning_id=planning.id,
        planning_version=planning.planning_version,
        planning_output_digest=planning.provenance.output_digest,
        planning_reviewed_at=planning.reviewed_at,
        planning_reviewed_by=planning.reviewed_by,
        case_source_digest=snapshot.source_digest,
        case_snapshot_version=snapshot.case_snapshot_version,
        case_snapshot_contract_version=snapshot.contract_version,
        risk_engine_version="1.0.0",
        risk_policy_version="observed-facts-v1",
        risk_input_digest=risk.input_digest,
        risk_result_digest=risk.result_digest,
        contract_version="1.0",
        engine_version="1.0.0",
    )

    AISecondReviewService._assert_reviewable_chain(
        planning_row=planning_row,
        simulation_row=simulation_row,
        snapshot=snapshot,
        risk_evaluation=risk,
        planning=planning,
        simulation=simulation,
    )

    original_input_digest = simulation.provenance.input_digest
    simulation.provenance.input_digest = "sha256:" + "8" * 64
    with pytest.raises(SecondReviewSafetyError, match="simulation_input_digest_mismatch"):
        AISecondReviewService._assert_reviewable_chain(
            planning_row=planning_row,
            simulation_row=simulation_row,
            snapshot=snapshot,
            risk_evaluation=risk,
            planning=planning,
            simulation=simulation,
        )
    simulation.provenance.input_digest = original_input_digest

    simulation_row.risk_result_digest = "sha256:" + "9" * 64
    with pytest.raises(SecondReviewSafetyError, match="second_review_artifact_chain_is_stale"):
        AISecondReviewService._assert_reviewable_chain(
            planning_row=planning_row,
            simulation_row=simulation_row,
            snapshot=snapshot,
            risk_evaluation=risk,
            planning=planning,
            simulation=simulation,
        )
