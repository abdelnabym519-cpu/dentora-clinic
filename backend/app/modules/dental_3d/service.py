"""Dental 3D scene service — application layer.

Business logic only, no HTTP concerns (static methods on the class per
repo convention). Every query filters by ``clinic_id``.

ADR 0020: the service asks the ``DentalGeometrySource`` **port** for
geometry and never touches the providers' infrastructure. The default
wiring (``default_sources``) is imported lazily at call time — the
composition root stays at the infrastructure edge, routers/tests may
inject explicit sources, and module imports stay acyclic.

Scene assembly:

- **Teeth** come from the first source that provides them — the
  synthetic source (Phase 1 behaviour, unchanged): every permanent
  tooth starts ``healthy``/present, recorded conditions are overlaid
  (``missing`` marks the tooth absent). A persisted
  :class:`DentalScene` row stores per-tooth view overrides merged on
  top, so re-recording a condition in the odontogram keeps driving
  presence/condition while 3D view state is preserved independently.
- **Meshes** (Phase 2) are aggregated from every source — real
  intraoral-scan references discovered from the media module. When at
  least one real mesh exists the scene ``generator`` reports
  ``intraoral_scan``; the synthetic teeth remain in the payload as the
  viewer's fallback.

``DentalMeshService.ingest`` is the upload use case: validates a mesh
file (extension + MIME + content sniff, see ``meshfiles.py``) and
stores it through the **media** module's ``DocumentService`` — the one
existing storage system; dental_3d never writes files itself.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .meshfiles import MeshUploadError, canonical_mime, detect_mesh_format, mesh_download_url
from .models import DentalScene as DentalSceneRow
from .schemas import (
    DentalMesh,
    DentalSceneResponse,
    DentalSceneUpdate,
    SegmentationResult,
    Tooth3D,
)
from .sources import DentalGeometrySource, GeometryProvision


def _merge(overrides: list[Tooth3D], defaults: list[Tooth3D]) -> list[Tooth3D]:
    """Overlay persisted per-tooth view state on the synthesised defaults.

    Overrides win per tooth number; teeth only present in the defaults
    keep their synthesised state. Teeth only present in the overrides
    (e.g. the odontogram record was deleted since the save) are kept so
    no view state is silently dropped.
    """
    by_number = {t.tooth_number: t for t in overrides}
    merged: list[Tooth3D] = []
    for default in defaults:
        override = by_number.pop(default.tooth_number, None)
        if override is None:
            merged.append(default)
            continue
        # Condition/presence stay odontogram-driven; view state persists.
        merged.append(
            Tooth3D(
                tooth_number=default.tooth_number,
                present=default.present,
                condition=default.condition,
                color=override.color,
                visible=override.visible,
                mesh=override.mesh,
            )
        )
    merged.extend(by_number.values())
    merged.sort(key=lambda t: t.tooth_number)
    return merged


def _segmentation_of(row: DentalSceneRow | None) -> SegmentationResult:
    """Segmentation is a future capability — Phase 2 always reports N/A."""
    return SegmentationResult(status="not_available")


async def _provisions(
    db: AsyncSession,
    clinic_id: UUID,
    patient_id: UUID,
    sources: list[DentalGeometrySource] | tuple[DentalGeometrySource, ...] | None,
) -> list[GeometryProvision]:
    """Collect provisions from the given sources (or the default wiring)."""
    if sources is None:
        # Composition root — infrastructure edge, imported lazily so the
        # application layer's import graph never points outward.
        from .infrastructure import default_sources

        sources = default_sources(db)
    return [await source.provide(clinic_id, patient_id) for source in sources]


class DentalSceneService:
    """Static service layer for dental 3D scenes."""

    @staticmethod
    async def _load_row(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> DentalSceneRow | None:
        stmt = select(DentalSceneRow).where(
            DentalSceneRow.clinic_id == clinic_id,
            DentalSceneRow.patient_id == patient_id,
            DentalSceneRow.status == "active",
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_for_patient(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        sources: list[DentalGeometrySource] | tuple[DentalGeometrySource, ...] | None = None,
    ) -> DentalSceneResponse:
        """Return the patient's scene: geometry provisions + persisted view state."""
        provisions = await _provisions(db, clinic_id, patient_id, sources)

        # First source with teeth defines the default dentition.
        defaults: list[Tooth3D] = next((p.teeth for p in provisions if p.teeth), [])
        # Real meshes aggregate from every source (synthetic adds none).
        meshes = [mesh for provision in provisions for mesh in provision.meshes]

        row = await DentalSceneService._load_row(db, clinic_id, patient_id)
        if row is None:
            return DentalSceneResponse(
                patient_id=patient_id,
                generator="intraoral_scan" if meshes else "synthetic",
                teeth=defaults,
                segmentation=_segmentation_of(None),
                meshes=meshes,
                persisted=False,
            )

        overrides = [Tooth3D.model_validate(t) for t in (row.teeth or [])]
        return DentalSceneResponse(
            id=row.id,
            patient_id=patient_id,
            # Real geometry, when present, defines the scene's provenance;
            # the persisted row keeps recording the view-state generator.
            generator="intraoral_scan" if meshes else row.generator,
            teeth=_merge(overrides, defaults),
            segmentation=_segmentation_of(row),
            meshes=meshes,
            updated_at=row.updated_at,
            persisted=True,
        )

    @staticmethod
    async def save_for_patient(
        db: AsyncSession,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        payload: DentalSceneUpdate,
        sources: list[DentalGeometrySource] | tuple[DentalGeometrySource, ...] | None = None,
    ) -> DentalSceneResponse:
        """Upsert the persisted scene (full replace of per-tooth view state)."""
        row = await DentalSceneService._load_row(db, clinic_id, patient_id)
        if row is None:
            row = DentalSceneRow(
                clinic_id=clinic_id,
                patient_id=patient_id,
                created_by=user_id,
            )
            db.add(row)

        row.generator = "synthetic"
        row.teeth = [t.model_dump(mode="json") for t in payload.teeth]
        row.segmentation = (
            payload.segmentation.model_dump(mode="json") if payload.segmentation else None
        )
        await db.commit()

        return await DentalSceneService.get_for_patient(db, clinic_id, patient_id, sources)


class DentalMeshService:
    """Ingestion use case: validated mesh file → media document → mesh reference."""

    @staticmethod
    async def ingest(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID,
        filename: str,
        content_type: str | None,
        data: bytes,
        title: str | None = None,
    ) -> DentalMesh:
        """Validate and store one mesh file; return its scene-level descriptor.

        Storage goes exclusively through the media module's
        ``DocumentService`` (the existing storage system — ownership,
        storage backend, events and archival are media's concerns).
        Raises :class:`MeshUploadError` on any validation failure.
        """
        if len(data) > settings.STORAGE_MAX_FILE_SIZE:
            raise MeshUploadError(
                "too_large: file exceeds the "
                f"{settings.STORAGE_MAX_FILE_SIZE // (1024 * 1024)}MB limit"
            )

        mesh_format = detect_mesh_format(filename, content_type, data)

        # Declared dependency (manifest.depends) — cross-module service
        # use is the repo's sanctioned integration path.
        from app.modules.media.service import DocumentService

        document = await DocumentService.create_document(
            db=db,
            clinic_id=clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            file_data=data,
            original_filename=filename,
            mime_type=canonical_mime(mesh_format),
            document_type="other",
            title=title or filename,
            media_kind="document",
        )
        return DentalMesh(
            source="intraoral_scan",
            format=mesh_format,  # type: ignore[arg-type]
            document_id=document.id,
            label=document.title,
            file_size=document.file_size,
            uploaded_at=document.created_at,
            url=mesh_download_url(document.id),
        )
