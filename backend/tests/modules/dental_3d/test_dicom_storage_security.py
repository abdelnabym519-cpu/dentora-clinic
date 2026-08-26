"""DICOM storage integrity and tenant-boundary regression coverage."""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.patients.models import Patient


def _dicom_bytes() -> bytes:
    sop_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    dataset = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = CTImageStorage
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.FrameOfReferenceUID = generate_uid()
    dataset.Modality = "CT"
    dataset.PatientName = "Protected^Patient"
    dataset.PatientID = "external-id-must-not-leak"
    dataset.Rows = 32
    dataset.Columns = 32
    dataset.NumberOfFrames = 1
    dataset.PixelSpacing = [0.3, 0.3]
    dataset.SliceThickness = 0.3
    dataset.ImagePositionPatient = [0.0, 0.0, 1.0]
    dataset.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]

    stream = BytesIO()
    dataset.save_as(stream, enforce_file_format=True)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_dicom_upload_download_preserves_raw_binary(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
) -> None:
    payload = _dicom_bytes()
    upload = await client.post(
        f"/api/v1/dental_3d/patients/{test_patient.id}/cbct/dicom-instances",
        headers=auth_headers,
        files={"file": ("cbct-slice.dcm", payload, "application/dicom")},
    )

    assert upload.status_code == 201
    document_id = upload.json()["data"]["document_id"]

    download = await client.get(
        f"/api/v1/media/documents/{document_id}/download",
        headers=auth_headers,
    )
    assert download.status_code == 200
    assert download.content == payload
    assert download.headers["content-type"] == "application/dicom"


@pytest.mark.asyncio
async def test_dicom_upload_cannot_target_patient_in_another_clinic(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    other_clinic = Clinic(
        id=uuid4(),
        name="Other DICOM Clinic",
        tax_id=f"DICOM-{uuid4().hex[:12]}",
        settings={},
    )
    db_session.add(other_clinic)
    await db_session.flush()
    other_patient = Patient(
        id=uuid4(),
        clinic_id=other_clinic.id,
        first_name="Other",
        last_name="Patient",
    )
    db_session.add(other_patient)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/dental_3d/patients/{other_patient.id}/cbct/dicom-instances",
        headers=auth_headers,
        files={"file": ("cbct-slice.dcm", _dicom_bytes(), "application/dicom")},
    )

    assert response.status_code == 404
