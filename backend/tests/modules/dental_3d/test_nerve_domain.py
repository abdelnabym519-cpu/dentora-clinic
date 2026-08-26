"""Phase 5.2 nerve-detection contract tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.nerve import (
    NerveConfidenceSummary,
    NerveDetectionFailure,
    NerveDetectionFailureCode,
    NerveDetectionProvider,
    NerveDetectionRequest,
    NerveDetectionResult,
    NerveEvidence,
    NerveModelProvenance,
    NervePathPoint,
    NervePathway,
    NerveReferenceSpace,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
FRAME_UID = "1.2.3.4"


def _path(*, confidence: float = 0.9, status: str = "detected") -> NervePathway:
    return NervePathway(
        finding_id="finding-left",
        side="left",
        source="model_inference",
        status=status,
        confidence=confidence,
        reference_space=NerveReferenceSpace(
            kind="dicom_patient", unit="mm", frame_of_reference_uid=FRAME_UID
        ),
        points=[NervePathPoint(x=1, y=2, z=3), NervePathPoint(x=4, y=5, z=6)],
        evidence=NerveEvidence(basis="cbct_inference", backing_documents=[uuid4()]),
    )


def _provenance() -> NerveModelProvenance:
    return NerveModelProvenance(
        model_id="detector",
        model_version="1",
        adapter="dentora-cbct-http-v1",
        input_digest="sha256:" + "a" * 64,
        study_instance_uid="1.2.3",
        series_instance_uid="1.2.3.1",
        frame_of_reference_uid=FRAME_UID,
    )


def _confidence(value: float = 0.9) -> NerveConfidenceSummary:
    return NerveConfidenceSummary(count=1, minimum=value, maximum=value, mean=value)


def test_provider_protocol_is_replaceable() -> None:
    class Stub:
        name = "stub"
        input_kind = "cbct_series"

        async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
            raise NotImplementedError

    assert isinstance(Stub(), NerveDetectionProvider)


def test_detected_model_result_requires_native_geometry_and_provenance() -> None:
    result = NerveDetectionResult(
        status="detected",
        provider="service",
        method="model",
        input_kind="cbct_series",
        requires_review=True,
        pathways=[_path()],
        provenance=_provenance(),
        confidence_summary=_confidence(),
        performed_at=NOW,
    )
    assert result.is_clinical is False
    assert result.proximities == []
    with pytest.raises(ValidationError):
        NerveDetectionResult(
            status="detected",
            provider="service",
            method="model",
            input_kind="cbct_series",
            requires_review=True,
            pathways=[_path()],
            confidence_summary=_confidence(),
            performed_at=NOW,
        )


def test_model_result_forbids_unaligned_tooth_proximity() -> None:
    from app.modules.dental_3d.nerve import ToothNerveProximity

    with pytest.raises(ValidationError, match="alignment"):
        NerveDetectionResult(
            status="detected",
            provider="service",
            method="model",
            input_kind="cbct_series",
            requires_review=True,
            pathways=[_path()],
            proximities=[
                ToothNerveProximity(
                    tooth_number=36,
                    side="left",
                    distance_mm=1,
                    closest_point_index=0,
                    warning="near",
                    confidence=0.9,
                )
            ],
            provenance=_provenance(),
            confidence_summary=_confidence(),
            performed_at=NOW,
        )


def test_failure_is_explicit_non_anatomical_and_not_reviewable() -> None:
    result = NerveDetectionResult(
        status="failed",
        provider="service",
        method="model",
        input_kind="cbct_series",
        requires_review=False,
        failure=NerveDetectionFailure(
            code=NerveDetectionFailureCode.MISSING_MODEL,
            message="No model is configured",
        ),
        performed_at=NOW,
    )
    assert result.pathways == []
    with pytest.raises(ValidationError):
        NerveDetectionResult(
            status="failed",
            provider="service",
            method="model",
            input_kind="cbct_series",
            requires_review=True,
            failure=result.failure,
            performed_at=NOW,
        )


def test_no_detection_is_not_a_failure_and_requires_review() -> None:
    result = NerveDetectionResult(
        status="no_detection",
        provider="service",
        method="model",
        input_kind="cbct_series",
        requires_review=True,
        provenance=_provenance(),
        performed_at=NOW,
    )
    assert result.failure is None
    assert result.requires_review is True


def test_uncertain_outcome_requires_uncertain_finding() -> None:
    result = NerveDetectionResult(
        status="uncertain",
        provider="service",
        method="model",
        input_kind="cbct_series",
        requires_review=True,
        pathways=[_path(confidence=0.4, status="uncertain")],
        provenance=_provenance(),
        confidence_summary=_confidence(0.4),
        performed_at=NOW,
    )
    assert len(result.uncertain) == 1


def test_dicom_space_needs_frame_and_points_are_finite_and_distinct() -> None:
    with pytest.raises(ValidationError):
        NerveReferenceSpace(kind="dicom_patient", unit="mm")
    with pytest.raises(ValidationError):
        NervePathPoint(x=float("nan"), y=0, z=0)
    with pytest.raises(ValidationError):
        NervePathway(
            finding_id="same",
            side="left",
            source="model_inference",
            status="detected",
            confidence=0.9,
            reference_space=NerveReferenceSpace(
                kind="dicom_patient", unit="mm", frame_of_reference_uid=FRAME_UID
            ),
            points=[NervePathPoint(x=1, y=1, z=1), NervePathPoint(x=1, y=1, z=1)],
            evidence=NerveEvidence(basis="cbct_inference"),
        )
