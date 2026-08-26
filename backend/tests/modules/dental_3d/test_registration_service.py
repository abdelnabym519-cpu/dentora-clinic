"""Application and persistence tests for patient registration."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.dental_3d.models import DentalAlignmentResult as AlignmentRow
from app.modules.dental_3d.registration import (
    AlignmentResult,
    AlignmentReviewUpdate,
    AlignmentRunRequest,
    CoordinateFrame,
    ExtractedDentalAnatomy,
    GeometryProvenance,
    Point3D,
    PreparedCbctAnatomyInput,
    PreparedRegistrationInput,
    RegistrationGeometry,
    RegistrationMetrics,
    RegistrationProvenance,
    RigidTransform,
)
from app.modules.dental_3d.registration_service import AlignmentError, DentalAlignmentService
from app.modules.patients.models import Patient


def _cbct() -> PreparedCbctAnatomyInput:
    return PreparedCbctAnatomyInput(
        archive=b"deidentified-dicom",
        digest="sha256:" + "b" * 64,
        series_instance_uid="1.2.3.4",
        frame_of_reference_uid="1.2.3.5",
        document_ids=[uuid4()],
    )


class _InputPort:
    async def prepare(
        self, *, clinic_id: UUID, patient_id: UUID, request: AlignmentRunRequest
    ) -> PreparedRegistrationInput:
        return PreparedRegistrationInput(
            patient_id=patient_id,
            mesh_document_id=request.mesh_document_id,
            mesh_format="stl",
            mesh_bytes=b"real-ios-mesh",
            ios_units=request.ios_units,
            ios_digest="sha256:" + "a" * 64,
            cbct=_cbct(),
        )


class _AnatomyPort:
    async def extract(self, prepared: PreparedCbctAnatomyInput) -> ExtractedDentalAnatomy:
        return ExtractedDentalAnatomy(
            points_mm=[
                Point3D(x=0, y=0, z=0),
                Point3D(x=1, y=0, z=0),
                Point3D(x=0, y=1, z=0),
            ],
            frame_of_reference_uid=prepared.frame_of_reference_uid,
            model_id="DentalSegmentator",
            model_version="test",
        )


class _RegistrationPort:
    name = "stub-registration"

    def register(self, geometry: RegistrationGeometry, performed_at: datetime) -> AlignmentResult:
        return AlignmentResult(
            patient_id=geometry.patient_id,
            status="pending_review",
            transform=RigidTransform(
                matrix=[[1, 0, 0, 4], [0, 1, 0, 5], [0, 0, 1, 6], [0, 0, 0, 1]]
            ),
            source_frame=CoordinateFrame(id=f"ios:{geometry.mesh_document_id}", kind="ios_mesh"),
            target_frame=CoordinateFrame(
                id="dicom:1.2.3.5",
                kind="dicom_patient",
                frame_of_reference_uid="1.2.3.5",
            ),
            algorithm="stub+icp",
            algorithm_version="test",
            provenance=RegistrationProvenance(
                ios=GeometryProvenance(
                    identifier=str(geometry.mesh_document_id),
                    digest=geometry.ios_digest,
                    document_ids=[geometry.mesh_document_id],
                    original_unit=geometry.ios_units,
                ),
                cbct=GeometryProvenance(
                    identifier=geometry.cbct.series_instance_uid,
                    digest=geometry.cbct.digest,
                    document_ids=geometry.cbct.document_ids,
                    original_unit="mm",
                ),
                anatomy_model_id=geometry.anatomy.model_id,
                anatomy_model_version=geometry.anatomy.model_version,
            ),
            metrics=RegistrationMetrics(
                initializer="open3d_ransac",
                source_point_count=100,
                target_point_count=120,
                feature_correspondence_count=80,
                inlier_correspondence_count=70,
                global_fitness=0.7,
                global_inlier_rmse_mm=1.1,
                icp_fitness=0.8,
                icp_inlier_rmse_mm=0.6,
                overlap_ratio=0.8,
                icp_iterations=5,
                icp_converged=True,
                outlier_ratio=0.125,
            ),
            performed_at=performed_at,
        )


class _FailingRegistrationPort:
    name = "failing-registration"

    def register(self, geometry: RegistrationGeometry, performed_at: datetime) -> AlignmentResult:
        raise RuntimeError("sensitive engine detail")


def _request() -> AlignmentRunRequest:
    return AlignmentRunRequest(
        mesh_document_id=uuid4(), series_instance_uid="1.2.3.4", ios_units="mm"
    )


async def _run(db: AsyncSession, patient: Patient) -> AlignmentResult:
    return await DentalAlignmentService.run_alignment(
        db,
        clinic_id=patient.clinic_id,
        patient_id=patient.id,
        user_id=None,
        request=_request(),
        input_port=_InputPort(),
        anatomy_port=_AnatomyPort(),
        registration_port=_RegistrationPort(),
    )


@pytest.mark.asyncio
async def test_success_is_persisted_pending_review(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    result = await _run(db_session, test_patient)
    assert result.status == "pending_review"
    assert result.transform is not None
    assert result.transform.matrix[0][3] == 4
    assert result.metrics is not None
    assert result.metrics.clinical_threshold_status == "CLINICAL_THRESHOLD_NOT_VALIDATED"
    row = (await db_session.execute(select(AlignmentRow))).scalar_one()
    assert row.provenance["ios"]["digest"] == "sha256:" + "a" * 64


@pytest.mark.asyncio
async def test_latest_history_and_review_workflow(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    first = await _run(db_session, test_patient)
    second = await _run(db_session, test_patient)
    latest = await DentalAlignmentService.latest_alignment(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert latest is not None and latest.id == second.id != first.id
    accepted = await DentalAlignmentService.review_alignment(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        alignment_id=second.id,
        reviewer_id=None,
        payload=AlignmentReviewUpdate(decision="accepted", note="checked in CBCT views"),
    )
    assert accepted.status == "accepted"
    assert accepted.reviewed_at is not None
    with pytest.raises(AlignmentError):
        await DentalAlignmentService.review_alignment(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            alignment_id=second.id,
            reviewer_id=None,
            payload=AlignmentReviewUpdate(decision="rejected"),
        )


@pytest.mark.asyncio
async def test_clinic_isolation(db_session: AsyncSession, test_patient: Patient) -> None:
    result = await _run(db_session, test_patient)
    other = Clinic(id=uuid4(), name="Other", tax_id="B00000009", address={}, settings={})
    db_session.add(other)
    await db_session.commit()
    assert (
        await DentalAlignmentService.latest_alignment(db_session, other.id, test_patient.id) is None
    )
    with pytest.raises(KeyError):
        await DentalAlignmentService.review_alignment(
            db_session,
            clinic_id=other.id,
            patient_id=test_patient.id,
            alignment_id=result.id,
            reviewer_id=None,
            payload=AlignmentReviewUpdate(decision="accepted"),
        )


@pytest.mark.asyncio
async def test_registration_failure_is_persisted_without_internal_detail(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    result = await DentalAlignmentService.run_alignment(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,
        request=_request(),
        input_port=_InputPort(),
        anatomy_port=_AnatomyPort(),
        registration_port=_FailingRegistrationPort(),
    )
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.code == "registration_failed"
    assert "sensitive" not in result.failure.message
