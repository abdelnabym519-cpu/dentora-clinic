"""Phase 2 — real mesh ingestion tests.

Covers:
- ``meshfiles`` validation rules (extension + MIME + content sniffing)
- the ``DentalGeometrySource`` port + synthetic adapter (Phase 1
  behaviour behind the abstraction) and injected fake sources
- the intraoral-scan adapter discovering mesh documents from media
- the upload endpoint (happy path, RBAC, ownership, bad inputs)
- scene assembly with real meshes (generator, synthetic fallback,
  clinic isolation, archival, non-mesh exclusion)
- PUT hardening: tooth-level mesh descriptors are server-derived
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.modules.dental_3d.infrastructure import (
    MAX_SCENE_MESHES,
    IntraoralScanGeometrySource,
    SyntheticGeometrySource,
    default_sources,
)
from app.modules.dental_3d.meshfiles import (
    MeshUploadError,
    canonical_mime,
    detect_mesh_format,
    format_for_mime,
    mesh_mimes,
)
from app.modules.dental_3d.schemas import DentalMesh, DentalSceneUpdate, Tooth3D
from app.modules.dental_3d.service import DentalMeshService, DentalSceneService
from app.modules.dental_3d.sources import DentalGeometrySource, GeometryProvision
from app.modules.media.models import Document as MediaDocument
from app.modules.media.service import DocumentService as MediaDocumentService
from app.modules.patients.models import Patient


def _binary_stl(triangles: int = 2) -> bytes:
    """Minimal valid binary STL: 80-byte header + count + 50 bytes/triangle."""
    return (
        b"dentora-test-stl".ljust(80, b"\0")
        + triangles.to_bytes(4, "little")
        + b"\0" * (50 * triangles)
    )


ASCII_STL = b"solid scan\nfacet normal 0 0 1\nouter loop\nendloop\nendfacet\nendsolid scan\n"
OBJ = b"# dentora test\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def _mesh_url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/meshes"


def _scene_url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/scene"


async def _upload(
    client: AsyncClient,
    headers: dict,
    patient_id,
    *,
    filename: str = "scan.stl",
    content: bytes | None = None,
    mime: str = "model/stl",
    title: str | None = None,
):
    data = content if content is not None else _binary_stl()
    files = {"file": (filename, data, mime)}
    form = {"title": title} if title else None
    return await client.post(_mesh_url(patient_id), headers=headers, files=files, data=form)


async def _clinic_admin_id(session: AsyncSession, clinic_id) -> UUID:
    row = (
        await session.execute(
            select(ClinicMembership.user_id).where(
                ClinicMembership.clinic_id == clinic_id, ClinicMembership.role == "admin"
            )
        )
    ).scalar_one()
    return row


async def _get_doc(session: AsyncSession, document_id) -> MediaDocument:
    return (
        await session.execute(select(MediaDocument).where(MediaDocument.id == document_id))
    ).scalar_one()


# ---------------------------------------------------------------------------
# meshfiles — pure validation rules
# ---------------------------------------------------------------------------


class TestMeshValidation:
    def test_binary_stl_accepted(self) -> None:
        assert detect_mesh_format("arch.stl", "model/stl", _binary_stl(3)) == "stl"

    def test_ascii_stl_accepted(self) -> None:
        assert detect_mesh_format("arch.stl", "model/stl", ASCII_STL) == "stl"

    def test_stl_octet_stream_accepted_and_canonicalised(self) -> None:
        fmt = detect_mesh_format("arch.stl", "application/octet-stream", _binary_stl())
        assert fmt == "stl"
        assert canonical_mime(fmt) == "model/stl"

    def test_obj_accepted(self) -> None:
        assert detect_mesh_format("arch.obj", "model/obj", OBJ) == "obj"
        assert canonical_mime("obj") == "model/obj"

    def test_unsupported_extension_rejected(self) -> None:
        with pytest.raises(MeshUploadError) as exc:
            detect_mesh_format("arch.ply", "application/octet-stream", b"whatever")
        assert exc.value.code == "unsupported_extension"

    def test_mime_mismatch_rejected(self) -> None:
        with pytest.raises(MeshUploadError) as exc:
            detect_mesh_format("scan.stl", "image/png", _binary_stl())
        assert exc.value.code == "mime_mismatch"

    def test_malformed_stl_rejected(self) -> None:
        bad = b"not an stl at all" + b"\x01\x00\x00\x00"  # wrong total length
        with pytest.raises(MeshUploadError) as exc:
            detect_mesh_format("scan.stl", "model/stl", bad)
        assert exc.value.code == "malformed_stl"

    def test_malformed_obj_rejected(self) -> None:
        with pytest.raises(MeshUploadError) as exc:
            detect_mesh_format("scan.obj", "model/obj", b"\x00\x01\x02binary junk")
        assert exc.value.code == "malformed_obj"

    def test_obj_without_faces_rejected(self) -> None:
        with pytest.raises(MeshUploadError) as exc:
            detect_mesh_format("scan.obj", "model/obj", b"v 0 0 0\nv 1 0 0\n")
        assert exc.value.code == "malformed_obj"

    def test_empty_file_rejected(self) -> None:
        with pytest.raises(MeshUploadError) as exc:
            detect_mesh_format("scan.stl", "model/stl", b"")
        assert exc.value.code == "empty_file"

    def test_discovery_vocabulary_is_canonical_only(self) -> None:
        assert mesh_mimes() == {"model/stl", "model/obj"}
        assert format_for_mime("model/stl") == "stl"
        assert format_for_mime("model/obj") == "obj"
        assert format_for_mime("application/pdf") is None


# ---------------------------------------------------------------------------
# Geometry source port + adapters
# ---------------------------------------------------------------------------


class _FakeSource:
    """Port conformance double — proves the service depends on the port only."""

    def __init__(self, name: str, provision: GeometryProvision) -> None:
        self.name = name
        self._provision = provision
        self.requested: list[tuple[str, str]] = []

    async def provide(self, clinic_id, patient_id) -> GeometryProvision:
        self.requested.append((str(clinic_id), str(patient_id)))
        return self._provision


class TestGeometrySources:
    @pytest.mark.asyncio
    async def test_synthetic_source_reproduces_phase1_dentition(
        self, db_session: AsyncSession, test_patient: Patient
    ) -> None:
        source = SyntheticGeometrySource(db_session)
        assert source.name == "synthetic"
        provision = await source.provide(test_patient.clinic_id, test_patient.id)
        assert provision.source == "synthetic"
        assert len(provision.teeth) == 32
        assert provision.meshes == []

    @pytest.mark.asyncio
    async def test_scan_source_empty_without_mesh_documents(
        self, db_session: AsyncSession, test_patient: Patient
    ) -> None:
        provision = await IntraoralScanGeometrySource(db_session).provide(
            test_patient.clinic_id, test_patient.id
        )
        assert provision.source == "intraoral_scan"
        assert provision.meshes == []
        assert provision.teeth == []

    def test_default_sources_are_port_conformant(self, db_session: AsyncSession) -> None:
        sources = default_sources(db_session)
        assert [s.name for s in sources] == ["synthetic", "intraoral_scan", "cbct"]
        assert all(isinstance(s, DentalGeometrySource) for s in sources)

    @pytest.mark.asyncio
    async def test_service_aggregates_injected_fake_sources(
        self, db_session: AsyncSession, test_patient: Patient
    ) -> None:
        teeth_source = _FakeSource(
            "synthetic",
            GeometryProvision(source="synthetic", teeth=[Tooth3D(tooth_number=11)]),
        )
        mesh_source = _FakeSource(
            "intraoral_scan",
            GeometryProvision(
                source="intraoral_scan",
                meshes=[
                    DentalMesh(
                        source="intraoral_scan",
                        format="stl",
                        document_id=uuid4(),
                        url="/api/v1/media/documents/x/download",
                    )
                ],
            ),
        )
        scene = await DentalSceneService.get_for_patient(
            db_session,
            test_patient.clinic_id,
            test_patient.id,
            sources=[teeth_source, mesh_source],
        )
        # Teeth from the first provider with teeth, meshes aggregated from
        # all, and every source saw exactly the clinic/patient it was asked.
        assert [t.tooth_number for t in scene.teeth] == [11]
        assert len(scene.meshes) == 1
        assert scene.meshes[0].source == "intraoral_scan"
        assert scene.generator == "intraoral_scan"
        assert all(len(s.requested) == 1 for s in (teeth_source, mesh_source))


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------


class TestMeshUploadEndpoint:
    @pytest.mark.asyncio
    async def test_upload_stl_creates_media_document(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_patient: Patient,
    ) -> None:
        response = await _upload(client, auth_headers, test_patient.id, title="Upper arch scan")
        assert response.status_code == 201
        mesh = response.json()["data"]
        assert mesh["source"] == "intraoral_scan"
        assert mesh["format"] == "stl"
        assert mesh["document_id"]
        assert mesh["label"] == "Upper arch scan"
        assert mesh["file_size"] == len(_binary_stl())
        assert mesh["url"].endswith(f"/api/v1/media/documents/{mesh['document_id']}/download")

        # Storage went through the media module — content round-trips.
        document = await _get_doc(db_session, mesh["document_id"])
        assert document.clinic_id == test_patient.clinic_id
        assert document.patient_id == test_patient.id
        assert document.mime_type == "model/stl"  # canonicalised
        assert document.document_type == "other"
        assert document.media_kind == "document"
        content = await MediaDocumentService.download_document(document)
        assert content == _binary_stl()

    @pytest.mark.asyncio
    async def test_upload_obj_accepted(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        response = await _upload(
            client,
            auth_headers,
            test_patient.id,
            filename="lower.obj",
            content=OBJ,
            mime="model/obj",
        )
        assert response.status_code == 201
        assert response.json()["data"]["format"] == "obj"

    @pytest.mark.asyncio
    async def test_upload_without_title_uses_filename(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        response = await _upload(client, auth_headers, test_patient.id, filename="arch.stl")
        assert response.status_code == 201
        assert response.json()["data"]["label"] == "arch.stl"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("filename", "content", "mime", "code"),
        [
            ("scan.ply", b"solid fake", "application/octet-stream", "unsupported_extension"),
            ("scan.stl", _binary_stl(), "image/png", "mime_mismatch"),
            ("scan.stl", b"junk-data-not-stl", "model/stl", "malformed_stl"),
            ("scan.obj", b"\x00\x01bin", "model/obj", "malformed_obj"),
            ("scan.stl", b"", "model/stl", "empty_file"),
        ],
    )
    async def test_invalid_uploads_rejected_400(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_patient: Patient,
        filename: str,
        content: bytes,
        mime: str,
        code: str,
    ) -> None:
        response = await _upload(
            client, auth_headers, test_patient.id, filename=filename, content=content, mime=mime
        )
        assert response.status_code == 400
        assert response.json()["message"].startswith(code)

    @pytest.mark.asyncio
    async def test_oversized_upload_rejected(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        from app.config import settings

        huge = b"\0" * (settings.STORAGE_MAX_FILE_SIZE + 1)
        response = await _upload(
            client, auth_headers, test_patient.id, filename="huge.stl", content=huge
        )
        assert response.status_code == 400
        assert response.json()["message"].startswith("too_large")

    @pytest.mark.asyncio
    async def test_write_permission_required(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_patient: Patient,
    ) -> None:
        viewer = User(
            id=uuid4(),
            email=f"viewer-{uuid4().hex[:8]}@test.clinic",
            password_hash=hash_password("TestPass1234"),
            first_name="View",
            last_name="Only",
        )
        db_session.add(viewer)
        await db_session.flush()
        db_session.add(
            ClinicMembership(
                id=uuid4(),
                user_id=viewer.id,
                clinic_id=test_patient.clinic_id,
                role="receptionist",
            )
        )
        await db_session.commit()
        token = create_access_token(viewer.id, token_version=viewer.token_version)

        response = await _upload(client, {"Authorization": f"Bearer {token}"}, test_patient.id)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_patient_404(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        response = await _upload(client, auth_headers, uuid4())
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_clinic_patient_404(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_patient: Patient,
    ) -> None:
        stranger_clinic = Clinic(
            id=uuid4(), name="Other Clinic", tax_id="B99999999", address={"city": "Nowhere"}
        )
        db_session.add(stranger_clinic)
        stranger_patient = Patient(
            id=uuid4(),
            clinic_id=stranger_clinic.id,
            first_name="Stranger",
            last_name="Patient",
            email="stranger@other.clinic",
            phone="+34600000001",
        )
        db_session.add(stranger_patient)
        await db_session.commit()
        response = await _upload(client, auth_headers, stranger_patient.id)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Scene assembly with real meshes
# ---------------------------------------------------------------------------


class TestSceneWithRealMeshes:
    @pytest.mark.asyncio
    async def test_scene_lists_uploaded_mesh_with_intraoral_generator(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        uploaded = (await _upload(client, auth_headers, test_patient.id)).json()["data"]
        response = await client.get(_scene_url(test_patient.id), headers=auth_headers)
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["generator"] == "intraoral_scan"
        assert len(payload["meshes"]) == 1
        mesh = payload["meshes"][0]
        assert mesh["document_id"] == uploaded["document_id"]
        assert mesh["source"] == "intraoral_scan"
        assert mesh["format"] == "stl"
        assert mesh["url"].endswith("/download")
        # Phase 1 contract intact: synthetic teeth still present as fallback.
        assert len(payload["teeth"]) == 32
        assert payload["segmentation"]["status"] == "not_available"

    @pytest.mark.asyncio
    async def test_scene_without_meshes_stays_synthetic(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        response = await client.get(_scene_url(test_patient.id), headers=auth_headers)
        payload = response.json()["data"]
        assert payload["generator"] == "synthetic"
        assert payload["meshes"] == []

    @pytest.mark.asyncio
    async def test_non_mesh_documents_never_surface(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_patient: Patient,
    ) -> None:
        await MediaDocumentService.create_document(
            db=db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            user_id=await _clinic_admin_id(db_session, test_patient.clinic_id),
            file_data=b"%PDF-1.7 fake",
            original_filename="report.pdf",
            mime_type="application/pdf",
            document_type="report",
            title="Report",
        )
        await db_session.commit()
        response = await client.get(_scene_url(test_patient.id), headers=auth_headers)
        assert response.json()["data"]["meshes"] == []

    @pytest.mark.asyncio
    async def test_other_clinic_meshes_invisible(
        self, db_session: AsyncSession, test_patient: Patient
    ) -> None:
        other_clinic = Clinic(
            id=uuid4(), name="Far Clinic", tax_id="B88888888", address={"city": "Elsewhere"}
        )
        db_session.add(other_clinic)
        other_patient = Patient(
            id=uuid4(),
            clinic_id=other_clinic.id,
            first_name="Other",
            last_name="Human",
            email="other.human@far.clinic",
            phone="+34600000002",
        )
        db_session.add(other_patient)
        other_user = User(
            id=uuid4(),
            email=f"far-{uuid4().hex[:8]}@test.clinic",
            password_hash=hash_password("TestPass1234"),
            first_name="Far",
            last_name="User",
        )
        db_session.add(other_user)
        await db_session.flush()
        await DentalMeshService.ingest(
            db_session,
            clinic_id=other_clinic.id,
            patient_id=other_patient.id,
            user_id=other_user.id,
            filename="theirs.stl",
            content_type="model/stl",
            data=_binary_stl(),
        )
        await db_session.commit()

        provision = await IntraoralScanGeometrySource(db_session).provide(
            test_patient.clinic_id, test_patient.id
        )
        assert provision.meshes == []

    @pytest.mark.asyncio
    async def test_archived_mesh_drops_out_of_scene(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_patient: Patient,
    ) -> None:
        mesh = await DentalMeshService.ingest(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            user_id=await _clinic_admin_id(db_session, test_patient.clinic_id),
            filename="old.stl",
            content_type="model/stl",
            data=_binary_stl(),
        )
        await db_session.commit()

        document = await _get_doc(db_session, mesh.document_id)
        document.status = "archived"
        await db_session.commit()

        response = await client.get(_scene_url(test_patient.id), headers=auth_headers)
        payload = response.json()["data"]
        assert payload["meshes"] == []
        assert payload["generator"] == "synthetic"

    @pytest.mark.asyncio
    async def test_meshes_sorted_newest_first_and_capped(
        self, db_session: AsyncSession, test_patient: Patient
    ) -> None:
        admin = await _clinic_admin_id(db_session, test_patient.clinic_id)
        doc_ids = []
        for index in range(MAX_SCENE_MESHES + 2):
            mesh = await DentalMeshService.ingest(
                db_session,
                clinic_id=test_patient.clinic_id,
                patient_id=test_patient.id,
                user_id=admin,
                filename=f"scan-{index}.stl",
                content_type="model/stl",
                data=_binary_stl(index + 1),
            )
            doc_ids.append(mesh.document_id)
            # Explicit backdating keeps ordering deterministic (the mixin
            # defaults created_at to now(), which can collide in fast tests).
            document = await _get_doc(db_session, mesh.document_id)
            document.created_at = datetime.utcnow() - timedelta(hours=MAX_SCENE_MESHES + 2 - index)
        await db_session.commit()

        scene = await DentalSceneService.get_for_patient(
            db_session, test_patient.clinic_id, test_patient.id
        )
        assert len(scene.meshes) == MAX_SCENE_MESHES
        # doc_ids is oldest→newest; the scene is newest→oldest, capped.
        assert [m.document_id for m in scene.meshes] == list(reversed(doc_ids))[:MAX_SCENE_MESHES]


# ---------------------------------------------------------------------------
# PUT hardening
# ---------------------------------------------------------------------------


class TestPutGuards:
    @pytest.mark.asyncio
    async def test_put_rejects_injected_tooth_mesh_reference(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        payload = {
            "teeth": [
                {
                    "tooth_number": 16,
                    "mesh": {
                        "source": "intraoral_scan",
                        "format": "stl",
                        "document_id": str(uuid4()),
                        "url": "/api/v1/media/documents/x/download",
                    },
                }
            ]
        }
        response = await client.put(_scene_url(test_patient.id), headers=auth_headers, json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_put_accepts_default_tooth_meshes(
        self, client: AsyncClient, auth_headers: dict, test_patient: Patient
    ) -> None:
        update = DentalSceneUpdate(teeth=[Tooth3D(tooth_number=16, visible=False)])
        response = await client.put(
            _scene_url(test_patient.id),
            headers=auth_headers,
            json=update.model_dump(mode="json"),
        )
        assert response.status_code == 200
