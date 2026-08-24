"""Phase 5.1 pydicom adapter and existing-media integration tests."""

from __future__ import annotations

from io import BytesIO
from uuid import UUID, uuid4

import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    CTImageStorage,
    ExplicitVRLittleEndian,
    MediaStorageDirectoryStorage,
    generate_uid,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import ClinicMembership
from app.modules.dental_3d.cbct import (
    DicomIngestionError,
    DicomIngestionErrorCode,
    DicomIngestionRequest,
)
from app.modules.dental_3d.infrastructure import (
    DICOM_MEDIA_MIME,
    DICOM_METADATA_KEY,
    PydicomMediaCbctAdapter,
    _read_dicom_metadata,
)
from app.modules.media.models import Document as MediaDocument
from app.modules.patients.models import Patient


def dicom_bytes(
    *,
    modality: str = "CT",
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    sop_class_uid: str = CTImageStorage,
    include_series_uid: bool = True,
    instance_number: int = 1,
) -> bytes:
    """Build a minimal Part 10 image containing header metadata only."""
    sop_uid = sop_uid or generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    dataset = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = sop_class_uid
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = study_uid or generate_uid()
    if include_series_uid:
        dataset.SeriesInstanceUID = series_uid or generate_uid()
    dataset.Modality = modality
    # These identifiers prove the adapter ignores identifying tags.
    dataset.PatientName = "Protected^Patient"
    dataset.PatientID = "external-id-123"
    dataset.Rows = 512
    dataset.Columns = 512
    dataset.NumberOfFrames = 1
    dataset.PixelSpacing = [0.3, 0.3]
    dataset.SliceThickness = 0.3
    dataset.ImagePositionPatient = [0.0, 0.0, float(instance_number)]
    dataset.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    dataset.Manufacturer = "Test Vendor"
    dataset.ManufacturerModelName = "CBCT Fixture"
    dataset.InstanceNumber = instance_number

    stream = BytesIO()
    dataset.save_as(stream, enforce_file_format=True)
    return stream.getvalue()


async def _clinic_admin_id(session: AsyncSession, clinic_id: UUID) -> UUID:
    return (
        await session.execute(
            select(ClinicMembership.user_id).where(
                ClinicMembership.clinic_id == clinic_id,
                ClinicMembership.role == "admin",
            )
        )
    ).scalar_one()


class TestPydicomHeaderAdapter:
    def test_extracts_normalized_geometry_metadata(self) -> None:
        metadata = _read_dicom_metadata(dicom_bytes())
        assert metadata.modality == "CT"
        assert metadata.rows == 512
        assert metadata.columns == 512
        assert metadata.pixel_spacing_mm == (0.3, 0.3)
        assert metadata.slice_thickness_mm == 0.3
        assert metadata.manufacturer == "Test Vendor"
        assert not hasattr(metadata, "PatientName")
        assert not hasattr(metadata, "patient_id")

    def test_rejects_non_part10_bytes(self) -> None:
        with pytest.raises(DicomIngestionError) as exc:
            _read_dicom_metadata(b"not dicom")
        assert exc.value.code is DicomIngestionErrorCode.MALFORMED_DICOM

    def test_rejects_non_ct_modality(self) -> None:
        with pytest.raises(DicomIngestionError) as exc:
            _read_dicom_metadata(dicom_bytes(modality="MR"))
        assert exc.value.code is DicomIngestionErrorCode.UNSUPPORTED_MODALITY

    def test_rejects_missing_required_series_uid(self) -> None:
        with pytest.raises(DicomIngestionError) as exc:
            _read_dicom_metadata(dicom_bytes(include_series_uid=False))
        assert exc.value.code is DicomIngestionErrorCode.MISSING_METADATA

    def test_rejects_dicomdir_explicitly(self) -> None:
        with pytest.raises(DicomIngestionError) as exc:
            _read_dicom_metadata(dicom_bytes(sop_class_uid=MediaStorageDirectoryStorage))
        assert exc.value.code is DicomIngestionErrorCode.UNSUPPORTED_DICOMDIR


class TestPydicomMediaAdapter:
    @pytest.mark.asyncio
    async def test_stores_raw_instance_in_existing_media_with_normalized_metadata(
        self,
        db_session: AsyncSession,
        test_patient: Patient,
    ) -> None:
        adapter = PydicomMediaCbctAdapter(db_session, max_file_size=10 * 1024 * 1024)
        data = dicom_bytes()
        receipt = await adapter.ingest(
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            user_id=await _clinic_admin_id(db_session, test_patient.clinic_id),
            request=DicomIngestionRequest(
                filename="cbct-slice.dcm",
                content_type="application/dicom",
                data=data,
                title="CBCT import",
            ),
        )

        document = (
            await db_session.execute(
                select(MediaDocument).where(MediaDocument.id == receipt.document_id)
            )
        ).scalar_one()
        assert document.clinic_id == test_patient.clinic_id
        assert document.patient_id == test_patient.id
        assert document.mime_type == DICOM_MEDIA_MIME
        assert document.file_size == len(data)
        assert document.tags == ["dental-3d", "cbct", "dicom"]
        envelope = document.extra_data[DICOM_METADATA_KEY]
        assert envelope["schema_version"] == 1
        assert envelope["metadata"]["series_instance_uid"] == (receipt.metadata.series_instance_uid)
        assert "PatientName" not in str(envelope)
        assert "external-id-123" not in str(envelope)
        assert receipt.download_url.endswith(f"/{document.id}/download")
        assert receipt.non_diagnostic is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("filename", "mime", "data", "expected"),
        [
            ("scan.zip", "application/octet-stream", b"data", "unsupported_extension"),
            ("scan.dcm", "image/png", b"data", "mime_mismatch"),
            ("scan.dcm", "application/dicom", b"", "empty_file"),
        ],
    )
    async def test_rejects_invalid_upload_before_storage(
        self,
        filename: str,
        mime: str,
        data: bytes,
        expected: str,
    ) -> None:
        # These gates execute before the adapter imports/calls media, so a
        # database is intentionally unnecessary for rejection coverage.
        adapter = PydicomMediaCbctAdapter(None, max_file_size=1024)  # type: ignore[arg-type]
        with pytest.raises(DicomIngestionError) as exc:
            await adapter.ingest(
                clinic_id=uuid4(),
                patient_id=uuid4(),
                user_id=uuid4(),
                request=DicomIngestionRequest(
                    filename=filename,
                    content_type=mime,
                    data=data,
                ),
            )
        assert exc.value.code.value == expected
