"""Phase 5.2 CBCT acquisition, sanitization and model-adapter tests."""

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4
from zipfile import ZipFile

import httpx
import pytest
from pydicom import dcmread
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from app.modules.dental_3d.cbct import (
    DICOM_METADATA_KEY,
    CbctSeriesDescriptor,
    DicomInstanceMetadata,
)
from app.modules.dental_3d.nerve import NerveDetectionRequest
from app.modules.dental_3d.nerve_inference import (
    CbctNerveDetectionProvider,
    HttpNerveInferenceEngine,
    NerveInferenceAdapterError,
    PreparedDicomSeries,
    UnavailableNerveInferenceEngine,
    _sanitized_dicom,
)
from app.modules.media.storage.base import StorageBackend

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
STUDY = "1.2.826.0.1.3680043.8.498.1"
SERIES = "1.2.826.0.1.3680043.8.498.2"
FRAME = "1.2.826.0.1.3680043.8.498.3"


def _dicom(*, sop: str, position: float) -> bytes:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = sop
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = sop
    ds.StudyInstanceUID = STUDY
    ds.SeriesInstanceUID = SERIES
    ds.FrameOfReferenceUID = FRAME
    ds.Modality = "CT"
    ds.PatientName = "Protected^Person"
    ds.PatientID = "MRN-SECRET"
    ds.StudyDescription = "identifying free text"
    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [0.3, 0.3]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, position]
    ds.PixelData = b"\x00\x00\x01\x00\x02\x00\x03\x00"
    output = BytesIO()
    ds.save_as(output, enforce_file_format=True)
    return output.getvalue()


def _metadata(*, sop: str, position: float) -> DicomInstanceMetadata:
    return DicomInstanceMetadata(
        modality="CT",
        sop_class_uid=str(CTImageStorage),
        study_instance_uid=STUDY,
        series_instance_uid=SERIES,
        sop_instance_uid=sop,
        transfer_syntax_uid=str(ExplicitVRLittleEndian),
        frame_of_reference_uid=FRAME,
        rows=2,
        columns=2,
        pixel_spacing_mm=(0.3, 0.3),
        image_orientation_patient=(1, 0, 0, 0, 1, 0),
        image_position_patient_mm=(0, 0, position),
    )


class _Scalars:
    def __init__(self, documents: list[SimpleNamespace]) -> None:
        self._documents = documents

    def all(self) -> list[SimpleNamespace]:
        return self._documents


class _QueryResult:
    def __init__(self, documents: list[SimpleNamespace]) -> None:
        self._documents = documents

    def scalars(self) -> _Scalars:
        return _Scalars(self._documents)


class _Db:
    def __init__(self, documents: list[SimpleNamespace]) -> None:
        self._documents = documents

    async def execute(self, _statement) -> _QueryResult:
        return _QueryResult(self._documents)


class _Storage(StorageBackend):
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values

    async def store(self, data: bytes, path: str) -> str:
        self.values[path] = data
        return path

    async def retrieve(self, path: str) -> bytes:
        return self.values[path]

    async def delete(self, path: str) -> bool:
        return self.values.pop(path, None) is not None

    async def exists(self, path: str) -> bool:
        return path in self.values


def _fixture() -> tuple[list[SimpleNamespace], _Storage, CbctSeriesDescriptor]:
    items: list[tuple[UUID, str, DicomInstanceMetadata, bytes]] = []
    for position in (2.0, 1.0):
        document_id = uuid4()
        sop = generate_uid()
        path = f"cbct/{document_id}.dcm"
        items.append(
            (
                document_id,
                path,
                _metadata(sop=sop, position=position),
                _dicom(sop=sop, position=position),
            )
        )
    documents = [
        SimpleNamespace(
            id=document_id,
            storage_path=path,
            extra_data={DICOM_METADATA_KEY: {"metadata": metadata.model_dump(mode="json")}},
        )
        for document_id, path, metadata, _ in items
    ]
    storage = _Storage({path: data for _, path, _, data in items})
    descriptor = CbctSeriesDescriptor(
        study_instance_uid=STUDY,
        series_instance_uid=SERIES,
        frame_of_reference_uid=FRAME,
        document_ids=[item[0] for item in items],
        instance_count=2,
        frame_count=2,
        rows=2,
        columns=2,
        latest_uploaded_at=NOW,
    )
    return documents, storage, descriptor


def _request(descriptor: CbctSeriesDescriptor) -> NerveDetectionRequest:
    return NerveDetectionRequest(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        cbct_series=[descriptor],
        performed_at=NOW,
    )


def test_dicom_sanitization_is_deterministic_and_removes_identifiers() -> None:
    raw = _dicom(sop=generate_uid(), position=1)
    first = _sanitized_dicom(raw)
    assert first == _sanitized_dicom(raw)
    parsed = dcmread(BytesIO(first))
    assert "PixelData" in parsed
    assert "PatientName" not in parsed
    assert "PatientID" not in parsed
    assert "StudyDescription" not in parsed


def test_sanitizer_rejects_unsupported_modality() -> None:
    raw = _dicom(sop=generate_uid(), position=1)
    parsed = dcmread(BytesIO(raw))
    parsed.Modality = "MR"
    output = BytesIO()
    parsed.save_as(output, enforce_file_format=True)
    with pytest.raises(NerveInferenceAdapterError) as error:
        _sanitized_dicom(output.getvalue())
    assert getattr(error.value, "code", None) == "unsupported_modality"


@pytest.mark.asyncio
async def test_full_adapter_orders_slices_calls_http_and_normalizes_native_finding() -> None:
    documents, storage, descriptor = _fixture()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-dentora-contract"] == "nerve-detection-v1"
        with ZipFile(BytesIO(await request.aread())) as archive:
            assert archive.namelist() == ["manifest.json", "0000.dcm", "0001.dcm"]
            first = dcmread(BytesIO(archive.read("0000.dcm")))
            second = dcmread(BytesIO(archive.read("0001.dcm")))
            assert float(first.ImagePositionPatient[2]) == 1.0
            assert float(second.ImagePositionPatient[2]) == 2.0
            assert "PatientName" not in first
        return httpx.Response(
            200,
            json={
                "status": "detected",
                "model_id": "test-canal-model",
                "model_version": "1.0",
                "findings": [
                    {
                        "finding_id": "left-1",
                        "side": "left",
                        "confidence": 0.91,
                        "points_mm": [
                            {"x": 1, "y": 2, "z": 3},
                            {"x": 4, "y": 5, "z": 6},
                        ],
                    }
                ],
            },
        )

    provider = CbctNerveDetectionProvider(
        db=_Db(documents),  # type: ignore[arg-type]
        storage=storage,
        engine=HttpNerveInferenceEngine(
            url="https://model.test/infer", transport=httpx.MockTransport(handler)
        ),
    )
    result = await provider.detect(_request(descriptor))
    assert result.status == "detected"
    assert result.pathways[0].reference_space.kind == "dicom_patient"
    assert result.pathways[0].reference_space.frame_of_reference_uid == FRAME
    assert result.proximities == []
    assert result.provenance is not None
    assert result.provenance.model_id == "test-canal-model"
    assert result.provenance.input_digest.startswith("sha256:")


@pytest.mark.asyncio
async def test_low_confidence_is_uncertain_and_malformed_output_is_failure() -> None:
    documents, storage, descriptor = _fixture()

    def response(confidence: float) -> dict:
        return {
            "status": "detected",
            "model_id": "model",
            "model_version": "1",
            "findings": [
                {
                    "side": "right",
                    "confidence": confidence,
                    "points_mm": [{"x": 1, "y": 2, "z": 3}, {"x": 2, "y": 3, "z": 4}],
                }
            ],
        }

    provider = CbctNerveDetectionProvider(
        db=_Db(documents),  # type: ignore[arg-type]
        storage=storage,
        engine=HttpNerveInferenceEngine(
            url="https://model.test/infer",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response(0.4))),
        ),
    )
    assert (await provider.detect(_request(descriptor))).status == "uncertain"

    provider = CbctNerveDetectionProvider(
        db=_Db(documents),  # type: ignore[arg-type]
        storage=storage,
        engine=HttpNerveInferenceEngine(
            url="https://model.test/infer",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"bad": True})),
        ),
    )
    result = await provider.detect(_request(descriptor))
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.code == "malformed_output"


@pytest.mark.asyncio
async def test_unconfigured_model_and_wrong_patient_series_fail_without_findings() -> None:
    documents, storage, descriptor = _fixture()
    provider = CbctNerveDetectionProvider(
        db=_Db(documents),  # type: ignore[arg-type]
        storage=storage,
        engine=UnavailableNerveInferenceEngine(),
    )
    missing = await provider.detect(_request(descriptor))
    assert missing.status == "failed"
    assert missing.failure is not None
    assert missing.failure.code == "missing_model"
    assert missing.pathways == []

    request = _request(descriptor)
    request.requested_series_instance_uid = "1.2.999"
    isolated = await provider.detect(request)
    assert isolated.status == "failed"
    assert isolated.failure is not None
    assert isolated.failure.code == "invalid_input"


@pytest.mark.asyncio
async def test_http_model_rejection_maps_to_safe_initialization_failure() -> None:
    _, _, descriptor = _fixture()
    prepared = PreparedDicomSeries(
        archive=b"zip",
        digest="sha256:" + "a" * 64,
        descriptor=descriptor,
        document_ids=tuple(descriptor.document_ids),
    )
    engine = HttpNerveInferenceEngine(
        url="https://model.test/infer",
        transport=httpx.MockTransport(lambda _: httpx.Response(422, text="secret detail")),
    )
    with pytest.raises(NerveInferenceAdapterError) as error:
        await engine.infer(prepared)
    assert getattr(error.value, "code", None) == "model_initialization_failed"
    assert "secret detail" not in getattr(error.value, "safe_message", "")
