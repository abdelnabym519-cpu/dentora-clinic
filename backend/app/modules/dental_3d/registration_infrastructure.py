"""Infrastructure adapters for patient-specific IOS→CBCT registration."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.media.models import Document as MediaDocument
from app.modules.media.storage import StorageBackend, get_storage_backend

from .cbct import DICOM_MEDIA_MIME, DICOM_METADATA_KEY, CbctSeriesDescriptor, DicomInstanceMetadata
from .infrastructure import CbctDicomGeometrySource
from .meshfiles import detect_mesh_format, format_for_mime, mesh_mimes
from .nerve_inference import _sanitized_dicom, _slice_position
from .registration import (
    AlignmentFailure,
    AlignmentFailureCode,
    AlignmentResult,
    AlignmentRunRequest,
    CoordinateFrame,
    DentalAnatomyPort,
    ExtractedDentalAnatomy,
    GeometryProvenance,
    Point3D,
    PreparedCbctAnatomyInput,
    PreparedRegistrationInput,
    RegistrationGeometry,
    RegistrationInputPort,
    RegistrationMetrics,
    RegistrationPort,
    RegistrationProvenance,
    RigidTransform,
)

REGISTRATION_ADAPTER_ID = "dentora-open3d-rigid-v1"
MAX_ANATOMY_RESPONSE_BYTES = 64 * 1024 * 1024
_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4}


class RegistrationAdapterError(Exception):
    """Expected adapter failure carrying client-safe detail."""

    def __init__(self, code: AlignmentFailureCode, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(code.value)


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_STORED
    info.external_attr = 0o600 << 16
    return info


class MediaRegistrationInputAdapter(RegistrationInputPort):
    """Load clinic/patient-owned IOS and de-identified CBCT inputs."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        storage: StorageBackend,
        max_instances: int,
        max_input_bytes: int,
    ) -> None:
        self._db = db
        self._storage = storage
        self._max_instances = max_instances
        self._max_input_bytes = max_input_bytes

    async def _select_series(
        self, clinic_id: UUID, patient_id: UUID, series_uid: str
    ) -> CbctSeriesDescriptor:
        provision = await CbctDicomGeometrySource(self._db).provide(clinic_id, patient_id)
        descriptor = next(
            (item for item in provision.cbct_series if item.series_instance_uid == series_uid),
            None,
        )
        if descriptor is None:
            raise RegistrationAdapterError(
                AlignmentFailureCode.MISSING_CBCT,
                "The requested CBCT series is not available for this patient",
            )
        if descriptor.catalog_truncated or descriptor.instance_count > self._max_instances:
            raise RegistrationAdapterError(
                AlignmentFailureCode.INVALID_GEOMETRY,
                "The selected CBCT series is incomplete or exceeds the registration limit",
            )
        if not descriptor.frame_of_reference_uid:
            raise RegistrationAdapterError(
                AlignmentFailureCode.MISSING_FRAME_OF_REFERENCE,
                "The CBCT series has no consistent DICOM Frame of Reference UID",
            )
        if descriptor.pixel_spacing_mm is None or any(
            value is None
            for value in (descriptor.rows, descriptor.columns, descriptor.slice_thickness_mm)
        ):
            raise RegistrationAdapterError(
                AlignmentFailureCode.INVALID_GEOMETRY,
                "The CBCT series has incomplete spacing or dimension metadata",
            )
        return descriptor

    async def _prepare_cbct(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        descriptor: CbctSeriesDescriptor,
    ) -> PreparedCbctAnatomyInput:
        stmt = select(MediaDocument).where(
            MediaDocument.id.in_(descriptor.document_ids),
            MediaDocument.clinic_id == clinic_id,
            MediaDocument.patient_id == patient_id,
            MediaDocument.status == "active",
            MediaDocument.mime_type == DICOM_MEDIA_MIME,
        )
        documents = list((await self._db.execute(stmt)).scalars().all())
        if len(documents) != len(descriptor.document_ids):
            raise RegistrationAdapterError(
                AlignmentFailureCode.MISSING_CBCT,
                "The selected CBCT series is incomplete",
            )

        instances: list[tuple[DicomInstanceMetadata, bytes]] = []
        total_bytes = 0
        for document in documents:
            envelope = (document.extra_data or {}).get(DICOM_METADATA_KEY)
            payload = envelope.get("metadata") if isinstance(envelope, dict) else None
            try:
                metadata = DicomInstanceMetadata.model_validate(payload)
            except ValidationError as exc:
                raise RegistrationAdapterError(
                    AlignmentFailureCode.INVALID_GEOMETRY,
                    "A stored CBCT instance has invalid normalized metadata",
                ) from exc
            if (
                metadata.series_instance_uid != descriptor.series_instance_uid
                or metadata.frame_of_reference_uid != descriptor.frame_of_reference_uid
                or metadata.pixel_spacing_mm is None
                or metadata.image_position_patient_mm is None
                or metadata.image_orientation_patient is None
            ):
                raise RegistrationAdapterError(
                    AlignmentFailureCode.INVALID_GEOMETRY,
                    "CBCT instance coordinate metadata is missing or inconsistent",
                )
            try:
                raw = await self._storage.retrieve(document.storage_path)
                sanitized = _sanitized_dicom(raw, metadata)
            except (FileNotFoundError, OSError) as exc:
                raise RegistrationAdapterError(
                    AlignmentFailureCode.MISSING_CBCT,
                    "A stored CBCT instance is unavailable",
                ) from exc
            total_bytes += len(raw)
            if total_bytes > self._max_input_bytes:
                raise RegistrationAdapterError(
                    AlignmentFailureCode.INVALID_GEOMETRY,
                    "The selected CBCT series exceeds the registration byte limit",
                )
            instances.append((metadata, sanitized))

        instances.sort(key=lambda item: _slice_position(item[0]))
        manifest = {
            "contract": "dentora-dental-anatomy-input-v1",
            "study_instance_uid": descriptor.study_instance_uid,
            "series_instance_uid": descriptor.series_instance_uid,
            "frame_of_reference_uid": descriptor.frame_of_reference_uid,
            "coordinate_system": "DICOM_PATIENT_LPS",
            "unit": "mm",
            "instances": [
                {
                    "file": f"{index:04d}.dcm",
                    "sop_instance_uid": metadata.sop_instance_uid,
                    "position_mm": metadata.image_position_patient_mm,
                    "orientation": metadata.image_orientation_patient,
                    "pixel_spacing_mm": metadata.pixel_spacing_mm,
                }
                for index, (metadata, _) in enumerate(instances)
            ],
        }
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(
                _zip_info("manifest.json"),
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
            )
            for index, (_, data) in enumerate(instances):
                archive.writestr(_zip_info(f"{index:04d}.dcm"), data)
        payload_bytes = buffer.getvalue()
        return PreparedCbctAnatomyInput(
            archive=payload_bytes,
            digest=f"sha256:{hashlib.sha256(payload_bytes).hexdigest()}",
            series_instance_uid=descriptor.series_instance_uid,
            frame_of_reference_uid=descriptor.frame_of_reference_uid,
            document_ids=list(descriptor.document_ids),
        )

    async def prepare(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        request: AlignmentRunRequest,
    ) -> PreparedRegistrationInput:
        descriptor = await self._select_series(clinic_id, patient_id, request.series_instance_uid)
        stmt = select(MediaDocument).where(
            MediaDocument.id == request.mesh_document_id,
            MediaDocument.clinic_id == clinic_id,
            MediaDocument.patient_id == patient_id,
            MediaDocument.status == "active",
            MediaDocument.mime_type.in_(mesh_mimes()),
        )
        document = (await self._db.execute(stmt)).scalar_one_or_none()
        if document is None:
            raise RegistrationAdapterError(
                AlignmentFailureCode.MISSING_IOS,
                "The requested IOS mesh is not available for this patient",
            )
        mesh_format = format_for_mime(document.mime_type)
        if mesh_format not in {"stl", "ply", "obj"}:
            raise RegistrationAdapterError(
                AlignmentFailureCode.MALFORMED_MESH,
                "The IOS mesh has an unsupported container format",
            )
        try:
            mesh_bytes = await self._storage.retrieve(document.storage_path)
            detected = detect_mesh_format(
                document.original_filename, document.mime_type, mesh_bytes
            )
        except (FileNotFoundError, OSError) as exc:
            raise RegistrationAdapterError(
                AlignmentFailureCode.MISSING_IOS,
                "The stored IOS mesh is unavailable",
            ) from exc
        except ValueError as exc:
            raise RegistrationAdapterError(
                AlignmentFailureCode.MALFORMED_MESH,
                "The stored IOS mesh failed validation",
            ) from exc
        if detected != mesh_format:
            raise RegistrationAdapterError(
                AlignmentFailureCode.MALFORMED_MESH,
                "The IOS mesh content does not match its stored format",
            )
        return PreparedRegistrationInput(
            patient_id=patient_id,
            mesh_document_id=document.id,
            mesh_format=mesh_format,
            mesh_bytes=mesh_bytes,
            ios_units=request.ios_units,
            ios_digest=f"sha256:{hashlib.sha256(mesh_bytes).hexdigest()}",
            cbct=await self._prepare_cbct(
                clinic_id=clinic_id,
                patient_id=patient_id,
                descriptor=descriptor,
            ),
        )


class _DentalAnatomyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    coordinate_system: str
    unit: str
    frame_of_reference_uid: str
    model_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    points_mm: list[Point3D] = Field(min_length=3, max_length=500_000)

    @model_validator(mode="after")
    def _explicit_patient_geometry(self) -> _DentalAnatomyResponse:
        if self.status != "completed":
            raise ValueError("anatomy extraction did not complete")
        if self.coordinate_system != "DICOM_PATIENT_LPS" or self.unit != "mm":
            raise ValueError("anatomy output must use DICOM patient LPS millimetres")
        return self


class HttpDentalSegmentatorAdapter(DentalAnatomyPort):
    """HTTP boundary around an operator-managed DentalSegmentator service."""

    def __init__(
        self,
        *,
        url: str,
        token: str = "",
        timeout_seconds: float = 900.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def extract(self, prepared: PreparedCbctAnatomyInput) -> ExtractedDentalAnatomy:
        headers = {
            "Content-Type": "application/zip",
            "Accept": "application/json",
            "X-Dentora-Input-Digest": prepared.digest,
            "X-Dentora-Contract": "dental-anatomy-v1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(self._url, content=prepared.archive, headers=headers)
        except httpx.RequestError as exc:
            raise RegistrationAdapterError(
                AlignmentFailureCode.ANATOMY_EXTRACTION_FAILED,
                "The DentalSegmentator service could not be reached",
            ) from exc
        if response.status_code >= 400:
            raise RegistrationAdapterError(
                AlignmentFailureCode.ANATOMY_EXTRACTION_FAILED,
                "The DentalSegmentator service rejected the input or failed",
            )
        try:
            length = int(response.headers.get("content-length", "0"))
        except ValueError:
            length = MAX_ANATOMY_RESPONSE_BYTES + 1
        if (
            length > MAX_ANATOMY_RESPONSE_BYTES
            or len(response.content) > MAX_ANATOMY_RESPONSE_BYTES
        ):
            raise RegistrationAdapterError(
                AlignmentFailureCode.ANATOMY_EXTRACTION_FAILED,
                "The DentalSegmentator response exceeded the allowed size",
            )
        try:
            parsed = _DentalAnatomyResponse.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise RegistrationAdapterError(
                AlignmentFailureCode.ANATOMY_EXTRACTION_FAILED,
                "The DentalSegmentator service returned malformed geometry",
            ) from exc
        if parsed.frame_of_reference_uid != prepared.frame_of_reference_uid:
            raise RegistrationAdapterError(
                AlignmentFailureCode.INVALID_GEOMETRY,
                "Dental anatomy frame does not match the selected CBCT series",
            )
        return ExtractedDentalAnatomy(
            points_mm=parsed.points_mm,
            frame_of_reference_uid=parsed.frame_of_reference_uid,
            model_id=parsed.model_id,
            model_version=parsed.model_version,
        )


class UnavailableDentalAnatomyAdapter(DentalAnatomyPort):
    async def extract(self, prepared: PreparedCbctAnatomyInput) -> ExtractedDentalAnatomy:
        raise RegistrationAdapterError(
            AlignmentFailureCode.DEPENDENCY_UNAVAILABLE,
            "No DentalSegmentator anatomy service is configured",
        )


@dataclass(frozen=True)
class _RegistrationCandidate:
    initializer: str
    transformation: object
    global_fitness: float
    global_rmse: float
    feature_correspondences: int


class Open3DRigidRegistrationAdapter(RegistrationPort):
    """Open3D global registration + optional TEASER++ + iterative ICP."""

    name = "open3d-rigid-registration"

    def __init__(
        self,
        *,
        voxel_size_mm: float = 1.0,
        global_distance_mm: float = 3.0,
        icp_distance_mm: float = 1.5,
        icp_max_iterations: int = 50,
    ) -> None:
        self._voxel_size = voxel_size_mm
        self._global_distance = global_distance_mm
        self._icp_distance = icp_distance_mm
        self._icp_max_iterations = icp_max_iterations

    @staticmethod
    def _libraries():
        try:
            import numpy as np
            import open3d as o3d
        except ImportError as exc:
            raise RegistrationAdapterError(
                AlignmentFailureCode.DEPENDENCY_UNAVAILABLE,
                "Open3D registration dependency is unavailable",
            ) from exc
        try:
            import teaserpp_python as teaser
        except ImportError:
            teaser = None
        return np, o3d, teaser

    @staticmethod
    def _load_source(o3d, np, geometry: RegistrationGeometry):
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=f".{geometry.mesh_format}", delete=False) as handle:
                handle.write(geometry.mesh_bytes)
                temporary_path = Path(handle.name)
            mesh = o3d.io.read_triangle_mesh(str(temporary_path), enable_post_processing=False)
            if mesh.is_empty() or len(mesh.vertices) < 3:
                raise RegistrationAdapterError(
                    AlignmentFailureCode.MALFORMED_MESH,
                    "Open3D could not decode IOS mesh vertices",
                )
            points = np.asarray(mesh.vertices, dtype=float) * _UNIT_TO_MM[geometry.ios_units]
            if not np.isfinite(points).all():
                raise RegistrationAdapterError(
                    AlignmentFailureCode.INVALID_GEOMETRY,
                    "IOS mesh contains non-finite coordinates",
                )
            points = np.unique(points, axis=0)
            if len(points) < 3 or np.linalg.matrix_rank(points - points.mean(axis=0)) < 2:
                raise RegistrationAdapterError(
                    AlignmentFailureCode.INVALID_GEOMETRY,
                    "IOS mesh geometry is degenerate",
                )
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(points)
            return cloud
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _target_cloud(o3d, np, geometry: RegistrationGeometry):
        points = np.asarray(
            [[point.x, point.y, point.z] for point in geometry.anatomy.points_mm],
            dtype=float,
        )
        points = np.unique(points, axis=0)
        if len(points) < 3 or not np.isfinite(points).all():
            raise RegistrationAdapterError(
                AlignmentFailureCode.INVALID_GEOMETRY,
                "DentalSegmentator anatomy point cloud is invalid",
            )
        if np.linalg.matrix_rank(points - points.mean(axis=0)) < 2:
            raise RegistrationAdapterError(
                AlignmentFailureCode.INVALID_GEOMETRY,
                "DentalSegmentator anatomy geometry is degenerate",
            )
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(points)
        return cloud

    def _preprocess(self, o3d, cloud):
        down = cloud.voxel_down_sample(self._voxel_size)
        if len(down.points) < 3:
            raise RegistrationAdapterError(
                AlignmentFailureCode.INVALID_GEOMETRY,
                "Geometry has too few points after deterministic downsampling",
            )
        down.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=self._voxel_size * 2.0, max_nn=30)
        )
        feature = o3d.pipelines.registration.compute_fpfh_feature(
            down,
            o3d.geometry.KDTreeSearchParamHybrid(radius=self._voxel_size * 5.0, max_nn=100),
        )
        return down, feature

    @staticmethod
    def _mutual_feature_correspondences(o3d, source_feature, target_feature):
        source_tree = o3d.geometry.KDTreeFlann(source_feature)
        target_tree = o3d.geometry.KDTreeFlann(target_feature)
        forward: dict[int, int] = {}
        for source_index in range(source_feature.num()):
            count, indices, _ = target_tree.search_knn_vector_xd(
                source_feature.data[:, source_index], 1
            )
            if count:
                forward[source_index] = indices[0]
        reverse: dict[int, int] = {}
        for target_index in range(target_feature.num()):
            count, indices, _ = source_tree.search_knn_vector_xd(
                target_feature.data[:, target_index], 1
            )
            if count:
                reverse[target_index] = indices[0]
        return [
            (source_index, target_index)
            for source_index, target_index in forward.items()
            if reverse.get(target_index) == source_index
        ]

    def _teaser_candidate(self, np, teaser, source, target, correspondences):
        if teaser is None or len(correspondences) < 3:
            return None
        try:
            parameters = teaser.RobustRegistrationSolver.Params()
            parameters.cbar2 = 1.0
            parameters.noise_bound = self._global_distance
            parameters.estimate_scaling = False
            parameters.rotation_estimation_algorithm = (
                teaser.RobustRegistrationSolver.ROTATION_ESTIMATION_ALGORITHM.GNC_TLS
            )
            parameters.rotation_gnc_factor = 1.4
            parameters.rotation_max_iterations = 100
            parameters.rotation_cost_threshold = 1e-12
            solver = teaser.RobustRegistrationSolver(parameters)
            source_points = np.asarray(source.points)[[item[0] for item in correspondences]].T
            target_points = np.asarray(target.points)[[item[1] for item in correspondences]].T
            solver.solve(source_points, target_points)
            solution = solver.getSolution()
            transformation = np.eye(4)
            transformation[:3, :3] = solution.rotation
            transformation[:3, 3] = solution.translation
            return transformation if np.isfinite(transformation).all() else None
        except Exception:
            # TEASER++ is an optional robust candidate. A binding/runtime
            # failure does not invalidate the independently measured RANSAC
            # candidate; the selected initializer is preserved in metrics.
            return None

    def _refine_icp(self, o3d, np, source, target, initial):
        current = np.asarray(initial, dtype=float)
        previous_rmse = math.inf
        converged = False
        result = None
        for iteration in range(1, self._icp_max_iterations + 1):
            result = o3d.pipelines.registration.registration_icp(
                source,
                target,
                self._icp_distance,
                current,
                o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=1),
            )
            updated = np.asarray(result.transformation, dtype=float)
            delta = float(np.linalg.norm(updated - current))
            rmse_delta = abs(previous_rmse - float(result.inlier_rmse))
            current = updated
            if delta <= 1e-7 and rmse_delta <= 1e-7:
                converged = True
                break
            previous_rmse = float(result.inlier_rmse)
        if result is None:
            raise RegistrationAdapterError(
                AlignmentFailureCode.REGISTRATION_FAILED,
                "ICP refinement did not execute",
            )
        return result, iteration, converged

    def register(self, geometry: RegistrationGeometry, performed_at: datetime) -> AlignmentResult:
        np, o3d, teaser = self._libraries()
        started = monotonic()
        source_full = self._load_source(o3d, np, geometry)
        target_full = self._target_cloud(o3d, np, geometry)
        source, source_feature = self._preprocess(o3d, source_full)
        target, target_feature = self._preprocess(o3d, target_full)
        o3d.utility.random.seed(0)
        correspondences = self._mutual_feature_correspondences(o3d, source_feature, target_feature)

        ransac = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
            source,
            target,
            source_feature,
            target_feature,
            True,
            self._global_distance,
            o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
            3,
            [
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(
                    self._global_distance
                ),
            ],
            o3d.pipelines.registration.RANSACConvergenceCriteria(100_000, 0.999),
        )
        candidates = [
            _RegistrationCandidate(
                initializer="open3d_ransac",
                transformation=ransac.transformation,
                global_fitness=float(ransac.fitness),
                global_rmse=float(ransac.inlier_rmse),
                feature_correspondences=len(correspondences),
            )
        ]
        teaser_transform = self._teaser_candidate(np, teaser, source, target, correspondences)
        if teaser_transform is not None:
            evaluation = o3d.pipelines.registration.evaluate_registration(
                source, target, self._global_distance, teaser_transform
            )
            candidates.append(
                _RegistrationCandidate(
                    initializer="teaser++",
                    transformation=teaser_transform,
                    global_fitness=float(evaluation.fitness),
                    global_rmse=float(evaluation.inlier_rmse),
                    feature_correspondences=len(correspondences),
                )
            )

        evaluated = []
        for candidate in candidates:
            result, iterations, converged = self._refine_icp(
                o3d, np, source, target, candidate.transformation
            )
            evaluated.append((candidate, result, iterations, converged))
        candidate, icp, iterations, converged = max(
            evaluated,
            key=lambda item: (float(item[1].fitness), -float(item[1].inlier_rmse)),
        )
        inlier_count = len(icp.correspondence_set)
        if inlier_count == 0 or not np.isfinite(icp.transformation).all():
            raise RegistrationAdapterError(
                AlignmentFailureCode.REGISTRATION_FAILED,
                "Registration produced no finite inlier transform",
            )
        transform = RigidTransform(matrix=np.asarray(icp.transformation).tolist())
        version = f"open3d={getattr(o3d, '__version__', 'unknown')}"
        if candidate.initializer == "teaser++":
            version += ";teaserpp=python-bindings"
        metrics = RegistrationMetrics(
            initializer=candidate.initializer,
            source_point_count=len(source.points),
            target_point_count=len(target.points),
            feature_correspondence_count=candidate.feature_correspondences,
            inlier_correspondence_count=inlier_count,
            global_fitness=candidate.global_fitness,
            global_inlier_rmse_mm=candidate.global_rmse,
            icp_fitness=float(icp.fitness),
            icp_inlier_rmse_mm=float(icp.inlier_rmse),
            overlap_ratio=float(icp.fitness),
            icp_iterations=iterations,
            icp_converged=converged,
            outlier_ratio=(
                1.0 - min(1.0, inlier_count / candidate.feature_correspondences)
                if candidate.feature_correspondences
                else 1.0
            ),
        )
        _ = monotonic() - started  # reserved for adapter telemetry, not a quality claim
        return AlignmentResult(
            patient_id=geometry.patient_id,
            status="pending_review" if converged else "uncertain",
            transform=transform,
            source_frame=CoordinateFrame(id=f"ios:{geometry.mesh_document_id}", kind="ios_mesh"),
            target_frame=CoordinateFrame(
                id=f"dicom-patient:{geometry.cbct.frame_of_reference_uid}",
                kind="dicom_patient",
                frame_of_reference_uid=geometry.cbct.frame_of_reference_uid,
            ),
            algorithm=f"{candidate.initializer}+open3d_icp",
            algorithm_version=version,
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
            metrics=metrics,
            performed_at=performed_at,
        )


def _validated_service_url(url: str) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    invalid = (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    )
    if invalid or (settings.ENVIRONMENT == "production" and parsed.scheme != "https"):
        return None
    return url


def default_registration_components(
    db: AsyncSession,
) -> tuple[RegistrationInputPort, DentalAnatomyPort, RegistrationPort]:
    storage = get_storage_backend()
    source = MediaRegistrationInputAdapter(
        db=db,
        storage=storage,
        max_instances=settings.DENTAL_3D_REGISTRATION_MAX_INSTANCES,
        max_input_bytes=settings.DENTAL_3D_REGISTRATION_MAX_INPUT_BYTES,
    )
    url = _validated_service_url(settings.DENTAL_3D_DENTAL_SEGMENTATOR_URL.strip())
    anatomy: DentalAnatomyPort = (
        HttpDentalSegmentatorAdapter(
            url=url,
            token=settings.DENTAL_3D_DENTAL_SEGMENTATOR_TOKEN,
            timeout_seconds=settings.DENTAL_3D_DENTAL_SEGMENTATOR_TIMEOUT_SECONDS,
        )
        if url
        else UnavailableDentalAnatomyAdapter()
    )
    registration = Open3DRigidRegistrationAdapter(
        voxel_size_mm=settings.DENTAL_3D_REGISTRATION_VOXEL_SIZE_MM,
        global_distance_mm=settings.DENTAL_3D_REGISTRATION_GLOBAL_DISTANCE_MM,
        icp_distance_mm=settings.DENTAL_3D_REGISTRATION_ICP_DISTANCE_MM,
        icp_max_iterations=settings.DENTAL_3D_REGISTRATION_ICP_MAX_ITERATIONS,
    )
    return source, anatomy, registration


def failed_alignment(
    *,
    patient_id: UUID,
    performed_at: datetime,
    code: AlignmentFailureCode,
    message: str,
) -> AlignmentResult:
    return AlignmentResult(
        patient_id=patient_id,
        status="failed",
        algorithm=REGISTRATION_ADAPTER_ID,
        algorithm_version="1",
        failure=AlignmentFailure(code=code, message=message),
        performed_at=performed_at,
        requires_review=False,
    )


__all__ = [
    "HttpDentalSegmentatorAdapter",
    "MediaRegistrationInputAdapter",
    "Open3DRigidRegistrationAdapter",
    "RegistrationAdapterError",
    "UnavailableDentalAnatomyAdapter",
    "default_registration_components",
    "failed_alignment",
]
