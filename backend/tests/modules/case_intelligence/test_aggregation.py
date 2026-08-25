"""Pure deterministic Case Intelligence aggregation tests."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.modules.case_intelligence.aggregation import CaseAggregator
from app.modules.case_intelligence.contracts import AvailabilityStatus

SECTIONS = (
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


def _available_sections() -> dict:
    sections = {}
    for name in SECTIONS:
        sections[name] = {
            "status": "available",
            "data": {"name": name, "value": 1},
            "evidence": [
                {
                    "source_module": "fixture",
                    "source_entity": name,
                    "source_record_id": f"{name}-1",
                    "source_version": "1",
                    "source_digest": "sha256:" + "a" * 64,
                }
            ],
        }
    sections["alignment"]["data"] = {
        "patient_space": {
            "target_frame": {
                "kind": "dicom_patient",
                "unit": "mm",
                "frame_of_reference_uid": "fixture-frame",
            },
            "transform": {
                "matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
            },
        }
    }
    return sections


def test_identical_input_produces_identical_aggregate_and_digest() -> None:
    clinic_id = uuid4()
    patient_id = uuid4()
    sections = _available_sections()

    first = CaseAggregator.aggregate(clinic_id=clinic_id, patient_id=patient_id, sections=sections)
    second = CaseAggregator.aggregate(
        clinic_id=clinic_id,
        patient_id=patient_id,
        sections=deepcopy(sections),
    )

    assert first == second
    assert first.source_digest == second.source_digest
    assert sections == _available_sections()


def test_source_change_changes_digest_without_clinical_inference() -> None:
    clinic_id = uuid4()
    patient_id = uuid4()
    sections = _available_sections()
    first = CaseAggregator.aggregate(clinic_id=clinic_id, patient_id=patient_id, sections=sections)

    changed = deepcopy(sections)
    changed["odontogram"]["data"]["value"] = 2
    second = CaseAggregator.aggregate(clinic_id=clinic_id, patient_id=patient_id, sections=changed)

    assert first.source_digest != second.source_digest
    assert "risk" not in second.model_dump_json().lower()
    assert "recommendation" not in second.model_dump_json().lower()


@pytest.mark.parametrize(
    "missing",
    ["anatomy", "nerve", "alignment", "ios", "prosthetic", "medical_context", "treatment_history"],
)
def test_missing_sources_are_explicit_not_available(missing: str) -> None:
    sections = _available_sections()
    sections[missing] = {
        "status": "not_available",
        "data": None,
        "evidence": [],
        "reason": f"{missing}_not_available",
    }
    result = CaseAggregator.aggregate(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        sections=sections,
    )

    assert result.availability[missing] == AvailabilityStatus.NOT_AVAILABLE
    assert missing in result.missing_data_report
    assert result.clinical_state[missing].data is None


def test_partial_mixed_availability_and_stale_source_are_preserved() -> None:
    sections = _available_sections()
    sections["nerve"] = {
        "status": "invalid_or_stale",
        "data": {"review_status": "pending"},
        "reason": "latest_nerve_pathway_not_validated",
        "evidence": [
            {
                "source_module": "dental_3d",
                "source_entity": "DentalNerveAnalysis",
                "source_record_id": "nerve-1",
                "source_version": "5",
                "validation_state": "detected:pending",
            }
        ],
    }
    sections["media"] = {"status": "not_available", "reason": "media_not_available"}
    result = CaseAggregator.aggregate(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        sections=sections,
    )

    assert result.availability["nerve"] == AvailabilityStatus.INVALID_OR_STALE
    assert result.availability["media"] == AvailabilityStatus.NOT_AVAILABLE
    assert result.clinical_state["nerve"].data == {"review_status": "pending"}


def test_patient_space_metadata_and_provenance_are_preserved() -> None:
    sections = _available_sections()
    result = CaseAggregator.aggregate(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        sections=sections,
    )

    assert result.reference_frame.status == AvailabilityStatus.AVAILABLE
    assert result.reference_frame.data["target_frame"]["unit"] == "mm"
    assert result.reference_frame.data["target_frame"]["frame_of_reference_uid"] == "fixture-frame"
    assert result.provenance
    assert result.source_versions["fixture.alignment.alignment-1"] == "1"


def test_missing_patient_space_metadata_is_invalid_not_inferred() -> None:
    sections = _available_sections()
    sections["alignment"]["data"] = {"patient_space": None}
    result = CaseAggregator.aggregate(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        sections=sections,
    )

    assert result.reference_frame.status == AvailabilityStatus.INVALID_OR_STALE
    assert result.reference_frame.data is None
    assert result.reference_frame.reason == "accepted_alignment_missing_patient_space_metadata"
