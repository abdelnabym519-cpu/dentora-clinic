"""Domain invariants for patient-specific rigid registration."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.registration import (
    AlignmentFailure,
    AlignmentResult,
    AlignmentRunRequest,
    CoordinateFrame,
    RigidTransform,
)


def test_identity_is_a_valid_se3_transform() -> None:
    transform = RigidTransform(
        matrix=[
            [1, 0, 0, 12.5],
            [0, 1, 0, -3.0],
            [0, 0, 1, 7.25],
            [0, 0, 0, 1],
        ]
    )
    assert transform.matrix[0][3] == 12.5


@pytest.mark.parametrize(
    "matrix",
    [
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 2, 0], [0, 0, 0, 1]],
        [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 1, 1]],
    ],
)
def test_scale_reflection_and_bad_homogeneous_row_are_rejected(matrix) -> None:
    with pytest.raises(ValidationError):
        RigidTransform(matrix=matrix)


def test_dicom_coordinate_frame_requires_frame_of_reference_uid() -> None:
    with pytest.raises(ValidationError, match="Frame of Reference"):
        CoordinateFrame(id="dicom", kind="dicom_patient")


def test_ios_units_are_explicit_and_never_defaulted() -> None:
    with pytest.raises(ValidationError):
        AlignmentRunRequest(
            mesh_document_id=uuid4(),
            series_instance_uid="1.2.3",
        )


def test_failed_alignment_forbids_transform_and_review() -> None:
    patient_id = uuid4()
    result = AlignmentResult(
        patient_id=patient_id,
        status="failed",
        algorithm="open3d",
        algorithm_version="1",
        failure=AlignmentFailure(code="invalid_geometry", message="geometry is ambiguous"),
        performed_at=datetime.now(UTC),
        requires_review=False,
    )
    assert result.transform is None
    with pytest.raises(ValidationError):
        AlignmentResult(
            patient_id=patient_id,
            status="failed",
            algorithm="open3d",
            algorithm_version="1",
            failure=AlignmentFailure(code="invalid_geometry", message="geometry is ambiguous"),
            transform=RigidTransform(
                matrix=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
            ),
            performed_at=datetime.now(UTC),
            requires_review=False,
        )
