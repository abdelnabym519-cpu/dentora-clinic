from datetime import UTC, datetime
from uuid import uuid4

from app.modules.case_intelligence.contracts import (
    AvailabilityStatus,
    CaseIdentity,
    CaseSection,
    CaseSnapshot,
    EvidenceReference,
)
from app.modules.risk_engine.engine import evaluate_snapshot


def _ref(module: str, entity: str, record: str, state: str = "accepted") -> EvidenceReference:
    return EvidenceReference(
        source_module=module,
        source_entity=entity,
        source_record_id=record,
        source_version="1",
        source_digest="sha256:" + "a" * 64,
        validation_state=state,
    )


def _snapshot() -> CaseSnapshot:
    clinic_id = uuid4()
    patient_id = uuid4()
    alignment_ref = _ref("dental_3d", "DentalAlignmentResult", "alignment-1")
    anatomy_ref = _ref("dental_3d", "DentalAlignmentResult", "alignment-1")
    nerve_ref = _ref("dental_3d", "DentalNerveAnalysis", "nerve-1")
    perio_ref = _ref("periodontogram", "PeriodontogramSnapshot", "perio-1", "closed")
    medical_ref = _ref("patients_clinical", "MedicalContext", "medical-1")
    plan_ref = _ref("dental_3d", "DentalImplantPlanRevision", "revision-1", "accepted")
    frame = {
        "source_frame": {"kind": "ios_mesh", "unit": "mm"},
        "target_frame": {
            "kind": "dicom_patient",
            "unit": "mm",
            "frame_of_reference_uid": "FRAME-1",
        },
        "transform": {
            "matrix": [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        },
    }
    clinical_state = {
        "alignment": CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={"patient_space": frame},
            evidence=[alignment_ref],
        ),
        "anatomy": CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={"model_id": "anatomy-1", "model_version": "1"},
            evidence=[anatomy_ref],
        ),
        "nerve": CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={
                "pathways": [
                    {
                        "reference_space": {
                            "kind": "dicom_patient",
                            "unit": "mm",
                            "frame_of_reference_uid": "FRAME-1",
                        },
                        "points": [
                            {"x": 0.0, "y": 0.0, "z": 0.0},
                            {"x": 5.0, "y": 0.0, "z": 0.0},
                        ],
                    }
                ]
            },
            evidence=[nerve_ref],
        ),
        "medical_context": CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={
                "context": {
                    "is_smoker": True,
                    "is_on_anticoagulants": False,
                    "bruxism": None,
                    "adverse_reactions_to_anesthesia": False,
                },
                "SystemicDisease": [
                    {"name": "ignored structured label", "notes": "free text is never evaluated"}
                ],
            },
            evidence=[medical_ref],
        ),
        "odontogram": CaseSection(status=AvailabilityStatus.NOT_AVAILABLE),
        "periodontogram": CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={
                "sites": [
                    {
                        "tooth_number": 36,
                        "site_code": "MB",
                        "bleeding_on_probing": True,
                        "plaque": False,
                        "suppuration": False,
                    }
                ]
            },
            evidence=[perio_ref],
        ),
        "implant_planning": CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data={
                "plans": [
                    {
                        "plan_id": "plan-1",
                        "status": "accepted",
                        "current_revision_number": 1,
                        "revision": {
                            "id": "revision-1",
                            "revision_number": 1,
                            "candidate": {
                                "center": {"x": 1.0, "y": 2.0, "z": 3.0},
                                "axis": {"x": 0.0, "y": 0.0, "z": 1.0},
                                "diameter_mm": 4.0,
                                "length_mm": 10.0,
                                "frame_of_reference_uid": "FRAME-1",
                                "unit": "mm",
                                "dimension_source": "dentist-explicit-dimensions",
                            },
                            "assessment": {
                                "intersects_nerve_centerline": True,
                            },
                        },
                    }
                ]
            },
            evidence=[plan_ref],
        ),
    }
    provenance = [alignment_ref, nerve_ref, perio_ref, medical_ref, plan_ref]
    return CaseSnapshot(
        case_snapshot_version=3,
        identity=CaseIdentity(clinic_id=clinic_id, patient_id=patient_id),
        reference_frame=CaseSection(
            status=AvailabilityStatus.AVAILABLE,
            data=frame,
            evidence=[alignment_ref],
        ),
        clinical_state=clinical_state,
        availability={name: section.status for name, section in clinical_state.items()},
        provenance=provenance,
        missing_data_report=["odontogram"],
        source_versions={"dental_3d.DentalAlignmentResult.alignment-1": "1"},
        source_digest="sha256:" + "b" * 64,
        generated_at=datetime.now(UTC),
    )


def test_deterministic_replay_and_explicit_factor_states():
    snapshot = _snapshot()
    first = evaluate_snapshot(snapshot)
    second = evaluate_snapshot(snapshot)

    assert first.input_digest == second.input_digest
    assert first.result_digest == second.result_digest
    factors = {factor.factor_id: factor for factor in first.factors}
    assert factors["smoking_context_present"].state == "present"
    assert factors["anticoagulant_context_present"].state == "absent"
    assert factors["bruxism_context_present"].state == "not_available"
    assert factors["periodontal_bleeding_observed"].state == "present"
    assert factors["periodontal_plaque_observed"].state == "absent"
    assert factors["accepted_implant_intersects_accepted_nerve_centerline"].state == "present"
    assert all(factor.evidence_ids or factor.state == "not_available" for factor in first.factors)


def test_patient_space_risk_map_uses_only_validated_evidence_and_no_synthetic_geometry():
    evaluation = evaluate_snapshot(_snapshot())

    assert evaluation.risk_map.status == "available"
    assert evaluation.risk_map.synthetic_geometry is False
    assert evaluation.risk_map.frame is not None
    assert evaluation.risk_map.frame.frame_of_reference_uid == "FRAME-1"
    assert {region.kind for region in evaluation.risk_map.regions} == {"polyline", "cylinder"}
    assert all(region.evidence_ids for region in evaluation.risk_map.regions)


def test_missing_or_stale_patient_space_fails_closed_without_geometry():
    snapshot = _snapshot()
    snapshot.reference_frame = CaseSection(
        status=AvailabilityStatus.INVALID_OR_STALE,
        reason="alignment_stale",
    )
    snapshot.clinical_state["alignment"] = CaseSection(
        status=AvailabilityStatus.INVALID_OR_STALE,
        reason="alignment_stale",
    )

    evaluation = evaluate_snapshot(snapshot)

    assert evaluation.risk_map.status == "unavailable"
    assert evaluation.risk_map.regions == []
    assert evaluation.risk_map.synthetic_geometry is False


def test_invalid_periodontal_source_is_not_zero_risk():
    snapshot = _snapshot()
    snapshot.clinical_state["periodontogram"] = CaseSection(
        status=AvailabilityStatus.INVALID_OR_STALE,
        reason="latest_periodontogram_not_closed",
    )

    evaluation = evaluate_snapshot(snapshot)
    factors = {factor.factor_id: factor for factor in evaluation.factors}

    assert factors["periodontal_bleeding_observed"].state == "invalid_or_stale"
    assert factors["periodontal_plaque_observed"].state == "invalid_or_stale"
    assert factors["periodontal_suppuration_observed"].state == "invalid_or_stale"


def test_relevant_source_change_changes_provenance_digests_without_clinical_scoring():
    first_snapshot = _snapshot()
    second_snapshot = first_snapshot.model_copy(deep=True)
    second_snapshot.clinical_state["medical_context"].data["context"]["is_smoker"] = False
    second_snapshot.source_digest = "sha256:" + "c" * 64

    first = evaluate_snapshot(first_snapshot)
    second = evaluate_snapshot(second_snapshot)

    assert first.input_digest != second.input_digest
    assert first.result_digest != second.result_digest
    assert not any(
        "score" in factor.factor_id or "high" in factor.factor_id for factor in second.factors
    )
