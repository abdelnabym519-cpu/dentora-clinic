"""Focused tests for registration infrastructure adapters."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.modules.dental_3d.cbct import CbctSeriesDescriptor
from app.modules.dental_3d.registration import (
    AlignmentRunRequest,
    ExtractedDentalAnatomy,
    Point3D,
    PreparedCbctAnatomyInput,
    RegistrationGeometry,
)
from app.modules.dental_3d.registration_infrastructure import (
    HttpDentalSegmentatorAdapter,
    MediaRegistrationInputAdapter,
    Open3DRigidRegistrationAdapter,
    RegistrationAdapterError,
)
from app.modules.dental_3d.sources import GeometryProvision


def _prepared_cbct() -> PreparedCbctAnatomyInput:
    return PreparedCbctAnatomyInput(
        archive=b"deidentified",
        digest="sha256:" + "c" * 64,
        series_instance_uid="1.2.3",
        frame_of_reference_uid="1.2.4",
        document_ids=[uuid4()],
    )


def _descriptor(frame_uid: str | None = "1.2.4") -> CbctSeriesDescriptor:
    return CbctSeriesDescriptor(
        study_instance_uid="1.2.2",
        series_instance_uid="1.2.3",
        frame_of_reference_uid=frame_uid,
        document_ids=[uuid4()],
        instance_count=1,
        frame_count=1,
        rows=32,
        columns=32,
        pixel_spacing_mm=(0.4, 0.4),
        slice_thickness_mm=0.4,
        latest_uploaded_at=datetime.now(UTC),
    )


class _Storage:
    async def retrieve(self, _path: str) -> bytes:
        return b"not-a-mesh"


class _Result:
    def __init__(self, document) -> None:
        self._document = document

    def scalar_one_or_none(self):
        return self._document


class _Db:
    def __init__(self, document=None) -> None:
        self._document = document

    async def execute(self, _statement):
        return _Result(self._document)


@pytest.mark.asyncio
async def test_registration_input_rejects_missing_frame_of_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Source:
        async def provide(self, _clinic_id, _patient_id):
            return GeometryProvision(source="cbct", cbct_series=[_descriptor(None)])

    monkeypatch.setattr(
        "app.modules.dental_3d.registration_infrastructure.CbctDicomGeometrySource",
        lambda _db: _Source(),
    )
    adapter = MediaRegistrationInputAdapter(
        db=_Db(), storage=_Storage(), max_instances=10, max_input_bytes=1024
    )
    with pytest.raises(RegistrationAdapterError) as exc:
        await adapter._select_series(uuid4(), uuid4(), "1.2.3")
    assert exc.value.code == "missing_frame_of_reference"


@pytest.mark.asyncio
async def test_registration_input_rejects_malformed_stored_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        mime_type="model/stl",
        storage_path="clinic/patient/scan.stl",
        original_filename="scan.stl",
    )
    adapter = MediaRegistrationInputAdapter(
        db=_Db(document), storage=_Storage(), max_instances=10, max_input_bytes=1024
    )

    async def selected(_clinic_id, _patient_id, _series_uid):
        return _descriptor()

    monkeypatch.setattr(adapter, "_select_series", selected)
    with pytest.raises(RegistrationAdapterError) as exc:
        await adapter.prepare(
            clinic_id=uuid4(),
            patient_id=uuid4(),
            request=AlignmentRunRequest(
                mesh_document_id=document_id,
                series_instance_uid="1.2.3",
                ios_units="mm",
            ),
        )
    assert exc.value.code == "malformed_mesh"


@pytest.mark.asyncio
async def test_dental_segmentator_adapter_preserves_patient_frame() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Dentora-Contract"] == "dental-anatomy-v1"
        assert request.headers["X-Dentora-Input-Digest"] == "sha256:" + "c" * 64
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "coordinate_system": "DICOM_PATIENT_LPS",
                "unit": "mm",
                "frame_of_reference_uid": "1.2.4",
                "model_id": "DentalSegmentator",
                "model_version": "v1",
                "points_mm": [
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 1, "y": 0, "z": 0},
                    {"x": 0, "y": 1, "z": 0},
                ],
            },
        )

    adapter = HttpDentalSegmentatorAdapter(
        url="https://segmentator.test/extract",
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.extract(_prepared_cbct())
    assert result.frame_of_reference_uid == "1.2.4"
    assert result.model_id == "DentalSegmentator"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("coordinate_system", "unit", "frame_uid"),
    [
        ("RAS", "mm", "1.2.4"),
        ("DICOM_PATIENT_LPS", "unknown", "1.2.4"),
        ("DICOM_PATIENT_LPS", "mm", "9.9.9"),
    ],
)
async def test_dental_segmentator_rejects_ambiguous_or_mismatched_geometry(
    coordinate_system: str, unit: str, frame_uid: str
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "coordinate_system": coordinate_system,
                "unit": unit,
                "frame_of_reference_uid": frame_uid,
                "model_id": "DentalSegmentator",
                "model_version": "v1",
                "points_mm": [
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 1, "y": 0, "z": 0},
                    {"x": 0, "y": 1, "z": 0},
                ],
            },
        )

    adapter = HttpDentalSegmentatorAdapter(
        url="https://segmentator.test/extract",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RegistrationAdapterError):
        await adapter.extract(_prepared_cbct())


def _ply(points: list[tuple[float, float, float]]) -> bytes:
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "element face 1",
        "property list uchar int vertex_indices",
        "end_header",
        *[f"{x} {y} {z}" for x, y, z in points],
        "3 0 1 2",
    ]
    return ("\n".join(lines) + "\n").encode()


def test_open3d_registration_handles_deterministic_outliers() -> None:
    pytest.importorskip("open3d")
    source = [
        (float(x), float(y), 0.15 * x * x + 0.08 * y * y + 0.03 * x * y)
        for x in range(8)
        for y in range(6)
    ]
    translation = (4.0, -3.0, 2.0)
    target = [
        Point3D(x=x + translation[0], y=y + translation[1], z=z + translation[2])
        for x, y, z in source
    ]
    target.extend(Point3D(x=100 + index, y=-80 + index * 2, z=50 - index) for index in range(12))
    cbct = _prepared_cbct()
    geometry = RegistrationGeometry(
        patient_id=uuid4(),
        mesh_document_id=uuid4(),
        mesh_format="ply",
        mesh_bytes=_ply(source),
        ios_units="mm",
        ios_digest="sha256:" + "d" * 64,
        cbct=cbct,
        anatomy=ExtractedDentalAnatomy(
            points_mm=target,
            frame_of_reference_uid=cbct.frame_of_reference_uid,
            model_id="DentalSegmentator",
            model_version="test",
        ),
    )
    result = Open3DRigidRegistrationAdapter(
        voxel_size_mm=0.5,
        global_distance_mm=2.0,
        icp_distance_mm=1.0,
        icp_max_iterations=30,
    ).register(geometry, datetime.now(UTC))
    assert result.transform is not None
    assert result.metrics is not None
    assert result.metrics.inlier_correspondence_count > 0
    assert result.metrics.outlier_ratio >= 0
    for axis, expected in enumerate(translation):
        assert result.transform.matrix[axis][3] == pytest.approx(expected, abs=1.0)
