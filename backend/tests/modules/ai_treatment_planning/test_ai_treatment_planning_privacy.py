from datetime import UTC, datetime
from uuid import uuid4

from app.modules.ai_treatment_planning.privacy import build_planning_llm_input
from app.modules.case_intelligence.contracts import (
    AvailabilityStatus,
    CaseIdentity,
    CaseSection,
    CaseSnapshot,
    EvidenceReference,
)
from app.modules.risk_engine.contracts import (
    RiskDisplayBand,
    RiskFactor,
    RiskFactorState,
    RiskMap,
)
from app.modules.risk_engine.engine import RiskEvaluation


def _snapshot() -> CaseSnapshot:
    patient_id = uuid4()
    clinic_id = uuid4()
    ref = EvidenceReference(
        source_module="odontogram",
        source_entity="ToothRecord",
        source_record_id=str(uuid4()),
        source_version="v1",
        source_digest="sha256:source",
        validation_state="current",
    )
    patient_ref = EvidenceReference(
        source_module="patients",
        source_entity="Patient",
        source_record_id=str(patient_id),
        source_version="v1",
    )
    return CaseSnapshot(
        case_snapshot_version=2,
        identity=CaseIdentity(clinic_id=clinic_id, patient_id=patient_id),
        reference_frame=CaseSection(
            status=AvailabilityStatus.NOT_AVAILABLE,
            reason="alignment_not_available",
        ),
        clinical_state={
            "patient": CaseSection(
                status=AvailabilityStatus.AVAILABLE,
                data={
                    "id": str(patient_id),
                    "date_of_birth": "1980-01-01",
                    "gender": "female",
                },
                evidence=[patient_ref],
            ),
            "odontogram": CaseSection(
                status=AvailabilityStatus.AVAILABLE,
                data={
                    "teeth": [
                        {
                            "id": str(uuid4()),
                            "tooth_number": 16,
                            "general_condition": "present",
                            "notes": "SENTINEL_CLINICAL_FREE_TEXT",
                            "description": "SENTINEL_DESCRIPTION",
                        }
                    ]
                },
                evidence=[ref],
            ),
            "nerve": CaseSection(
                status=AvailabilityStatus.INVALID_OR_STALE,
                reason="nerve_analysis_not_accepted",
            ),
        },
        availability={
            "patient": AvailabilityStatus.AVAILABLE,
            "odontogram": AvailabilityStatus.AVAILABLE,
            "nerve": AvailabilityStatus.INVALID_OR_STALE,
        },
        provenance=[patient_ref, ref],
        missing_data_report=["nerve:invalid_or_stale:nerve_analysis_not_accepted"],
        source_versions={
            "patients.Patient.x": "v1",
            "odontogram.ToothRecord.x": "v1",
        },
        source_digest="sha256:case",
        generated_at=datetime.now(UTC),
    )


def _risk() -> RiskEvaluation:
    factor = RiskFactor(
        factor_id="accepted_nerve_pathway_present",
        label="Accepted nerve pathway present",
        state=RiskFactorState.INVALID_OR_STALE,
        display_band=RiskDisplayBand.INVALID_SOURCE,
        evidence_ids=[],
        semantics="Observed-fact state only.",
    )
    return RiskEvaluation(
        factors=[factor],
        evidence=[],
        risk_map=RiskMap(status="unavailable", reason="alignment_not_available"),
        input_digest="sha256:risk-input",
        result_digest="sha256:risk-result",
        availability_state="invalid_or_stale",
    )


def test_planning_projection_excludes_identifiers_and_clinical_free_text():
    snapshot = _snapshot()
    payload, digest = build_planning_llm_input(snapshot, _risk())
    text = str(payload)
    assert str(snapshot.identity.patient_id) not in text
    assert str(snapshot.identity.clinic_id) not in text
    assert "SENTINEL_CLINICAL_FREE_TEXT" not in text
    assert "SENTINEL_DESCRIPTION" not in text
    assert "1980-01-01" not in text
    assert payload["case"]["sections"]["odontogram"]["data"]["teeth"][0]["tooth_number"] == 16
    assert payload["case"]["sections"]["nerve"]["status"] == "invalid_or_stale"
    assert set(payload["case"]["evidence"]) == {"E001", "E002"}
    assert payload["guardrails"]["no_treatment_simulation"] is True
    assert digest.startswith("sha256:")
