"""Phase 5.1 framework-independent CBCT/DICOM contract invariants."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.cbct import (
    CbctSeriesDescriptor,
    DicomIngestionError,
    DicomIngestionErrorCode,
    DicomIngestionPort,
    DicomIngestionReceipt,
    DicomIngestionRequest,
    DicomInstanceMetadata,
)
from app.modules.dental_3d.cbct_service import CbctIngestionService
from app.modules.dental_3d.schemas import DentalSceneUpdate


def _metadata(**overrides) -> DicomInstanceMetadata:
    values = {
        "modality": "CT",
        "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2",
        "study_instance_uid": "1.2.826.0.1.3680043.8.498.1",
        "series_instance_uid": "1.2.826.0.1.3680043.8.498.2",
        "sop_instance_uid": "1.2.826.0.1.3680043.8.498.3",
        "transfer_syntax_uid": "1.2.840.10008.1.2.1",
        "rows": 512,
        "columns": 512,
        "pixel_spacing_mm": (0.3, 0.3),
        "slice_thickness_mm": 0.3,
    }
    values.update(overrides)
    return DicomInstanceMetadata(**values)


class _RecordingPort:
    name = "recording"

    def __init__(self) -> None:
        self.calls = []

    async def ingest(self, *, clinic_id, patient_id, user_id, request):
        self.calls.append((clinic_id, patient_id, user_id, request))
        return DicomIngestionReceipt(
            document_id=uuid4(),
            download_url="/api/v1/media/documents/example/download",
            metadata=_metadata(),
        )


class TestDicomContracts:
    def test_normalized_metadata_contains_no_patient_identity(self) -> None:
        metadata = _metadata()
        assert metadata.source == "dicom"
        assert metadata.modality == "CT"
        identity_fields = {"patient_name", "patient_id", "patient_birth_date", "patient_sex"}
        assert identity_fields.isdisjoint(DicomInstanceMetadata.model_fields)

    @pytest.mark.parametrize("field", ["study_instance_uid", "series_instance_uid"])
    def test_rejects_invalid_uids(self, field: str) -> None:
        with pytest.raises(ValidationError):
            _metadata(**{field: "not-a-dicom-uid"})

    def test_rejects_uid_components_with_leading_zeroes(self) -> None:
        with pytest.raises(ValidationError):
            _metadata(series_instance_uid="1.02.3")

    def test_rejects_non_ct_modality(self) -> None:
        with pytest.raises(ValidationError):
            _metadata(modality="MR")

    def test_rejects_non_positive_spacing(self) -> None:
        with pytest.raises(ValidationError):
            _metadata(pixel_spacing_mm=(0.3, 0.0))

    def test_series_is_availability_only_and_non_diagnostic(self) -> None:
        descriptor = CbctSeriesDescriptor(
            study_instance_uid="1.2.3",
            series_instance_uid="1.2.3.4",
            document_ids=[uuid4()],
            instance_count=1,
            frame_count=1,
            latest_uploaded_at=datetime.now(UTC),
        )
        assert descriptor.status == "available"
        assert descriptor.catalog_truncated is False
        assert descriptor.non_diagnostic is True
        with pytest.raises(ValidationError):
            CbctSeriesDescriptor(
                study_instance_uid="1.2.3",
                series_instance_uid="1.2.3.4",
                document_ids=[uuid4()],
                instance_count=1,
                frame_count=1,
                latest_uploaded_at=datetime.now(UTC),
                non_diagnostic=False,
            )

    def test_error_contract_has_stable_code(self) -> None:
        error = DicomIngestionError(
            DicomIngestionErrorCode.UNSUPPORTED_MODALITY,
            "only CT is supported",
        )
        assert error.code is DicomIngestionErrorCode.UNSUPPORTED_MODALITY
        assert str(error).startswith("unsupported_modality:")

    def test_scene_update_rejects_client_supplied_cbct_series(self) -> None:
        with pytest.raises(ValidationError):
            DentalSceneUpdate.model_validate({"teeth": [], "cbct_series": []})


@pytest.mark.asyncio
async def test_application_service_depends_on_port_only() -> None:
    port = _RecordingPort()
    assert isinstance(port, DicomIngestionPort)
    service = CbctIngestionService(port)
    clinic_id, patient_id, user_id = uuid4(), uuid4(), uuid4()
    request = DicomIngestionRequest(
        filename="volume.dcm",
        content_type="application/dicom",
        data=b"dicom bytes",
    )

    receipt = await service.ingest(
        clinic_id=clinic_id,
        patient_id=patient_id,
        user_id=user_id,
        request=request,
    )

    assert receipt.non_diagnostic is True
    assert port.calls == [(clinic_id, patient_id, user_id, request)]
