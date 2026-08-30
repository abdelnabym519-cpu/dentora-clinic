from datetime import UTC, datetime
from uuid import uuid4

from app.modules.ai_case_summary.privacy import (
    build_provider_llm_input,
    build_redacted_llm_input,
)
from app.modules.case_intelligence.contracts import (
    AvailabilityStatus,
    CaseIdentity,
    CaseSection,
    CaseSnapshot,
    EvidenceReference,
)


def _snapshot() -> CaseSnapshot:
    patient_id = uuid4()
    clinic_id = uuid4()
    tooth_record_id = uuid4()
    ref = EvidenceReference(
        source_module="odontogram",
        source_entity="ToothRecord",
        source_record_id=str(tooth_record_id),
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
        case_snapshot_version=3,
        identity=CaseIdentity(clinic_id=clinic_id, patient_id=patient_id),
        reference_frame=CaseSection(
            status=AvailabilityStatus.NOT_AVAILABLE, reason="alignment_not_available"
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
                            "id": str(tooth_record_id),
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


def test_llm_projection_excludes_identifiers_and_free_text() -> None:
    snapshot = _snapshot()
    payload, digest = build_redacted_llm_input(snapshot)
    text = str(payload)
    assert str(snapshot.identity.patient_id) not in text
    assert str(snapshot.identity.clinic_id) not in text
    assert "SENTINEL_CLINICAL_FREE_TEXT" not in text
    assert "SENTINEL_DESCRIPTION" not in text
    assert "1980-01-01" not in text
    assert payload["sections"]["odontogram"]["data"]["teeth"][0]["tooth_number"] == 16
    assert payload["sections"]["nerve"]["status"] == "invalid_or_stale"
    assert set(payload["evidence"]) == {"E001", "E002"}
    assert digest.startswith("sha256:")


def test_provider_projection_preserves_evidence_ids_without_mutating_audit_payload() -> None:
    payload, _ = build_redacted_llm_input(_snapshot())
    provider_payload = build_provider_llm_input(payload)

    assert set(provider_payload["evidence"]) == set(payload["evidence"])

    # Each provider evidence alias exposes only facts from its own source record.
    assert provider_payload["evidence"]["E001"] == {
        "section": "odontogram",
        "facts": {
            "tooth_number": 16,
            "general_condition": "present",
        },
    }
    assert provider_payload["evidence"]["E002"] == {
        "section": "patient",
        "facts": {
            "gender": "female",
        },
    }

    # Canonical audit/provenance input remains complete and identifier-free.
    assert payload["evidence"]["E001"]["source_module"] == "odontogram"
    assert payload["evidence"]["E002"]["source_module"] == "patients"
    assert "source_record_id" not in str(payload)
    assert "1980-01-01" not in str(payload)

    # Provider has one and only one clinical-fact source: evidence[*].facts.
    assert all(
        "data" not in section
        for section in provider_payload["sections"].values()
    )
    assert "data" not in provider_payload["reference_frame"]

    # Availability/gap metadata remains available for deterministic handling.
    assert provider_payload["sections"]["nerve"]["status"] == "invalid_or_stale"
    assert provider_payload["sections"]["nerve"]["reason"] == "nerve_analysis_not_accepted"
    assert provider_payload["missing_data_report"] == payload["missing_data_report"]

    # Canonical audit input still retains its structured sections.
    assert "data" in payload["sections"]["odontogram"]
