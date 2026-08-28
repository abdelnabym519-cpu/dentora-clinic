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
- **CBCT series** (Phase 5.1) are aggregated as normalized availability only.
  They never change the render generator or synthetic fallback and contain no
  clinical inference.

``DentalMeshService.ingest`` is the upload use case: validates a mesh
file (extension + MIME + content sniff, see ``meshfiles.py``) and
stores it through the **media** module's ``DocumentService`` — the one
existing storage system; dental_3d never writes files itself.

``DentalSegmentationService`` (Phase 3, ADR 0021) runs the automatic
tooth-segmentation analysis through the ``ToothSegmentationProvider``
port and persists it with review state ``pending``; the dentist review
use case records the decision. Analyses are non-clinical decision
support: input → analysis → evidence/confidence → dentist review →
dentist decision, and a review never mutates odontogram records.

``DentalNerveService`` (Phase 5.2, ADR 0024) runs the replaceable CBCT
``NerveDetectionProvider`` and persists detected/no-detection/uncertain/failed
outcomes, provenance and native DICOM-patient geometry. Non-failed outputs
require dentist review; operational failures are explicitly non-reviewable.
No tooth alignment, proximity or surgical/implant planning occurs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .meshfiles import MeshUploadError, canonical_mime, detect_mesh_format, mesh_download_url
from .models import DentalNerveAnalysis as DentalNerveAnalysisRow
from .models import DentalScene as DentalSceneRow
from .models import DentalSegmentationAnalysis as DentalSegmentationAnalysisRow
from .nerve import (
    NerveConfidenceSummary,
    NerveDetectionAnalysisResponse,
    NerveDetectionFailure,
    NerveDetectionFailureCode,
    NerveDetectionProvider,
    NerveDetectionRequest,
    NerveDetectionResult,
    NerveModelProvenance,
    NervePathway,
    NerveReviewUpdate,
    ToothNerveProximity,
)
from .schemas import (
    DentalMesh,
    DentalSceneResponse,
    DentalSceneUpdate,
    NerveDetectionSummary,
    SegmentationResult,
    Tooth3D,
)
from .segmentation import (
    SegmentationAnalysisResponse,
    SegmentationRequest,
    SegmentationReviewUpdate,
    SegmentedTooth,
    ToothSegmentationProvider,
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


def _segmentation_of(
    row: DentalSceneRow | None,
    analysis: DentalSegmentationAnalysisRow | None,
) -> SegmentationResult:
    """Scene-level segmentation summary (Phase 3): latest analysis wins.

    No persisted analysis → ``not_available`` (Phases 1–2 behaviour).
    The summary is a projection of the analysis row — counts, provider,
    review state — never client-supplied input.
    """
    if analysis is None:
        return SegmentationResult(status="not_available")
    teeth = [SegmentedTooth.model_validate(t) for t in (analysis.teeth or [])]
    return SegmentationResult(
        status="completed",
        method=analysis.method,
        teeth_found=sum(1 for t in teeth if t.status == "segmented"),
        performed_at=analysis.performed_at,
        analysis_id=analysis.id,
        provider=analysis.provider,
        segmented_count=sum(1 for t in teeth if t.status == "segmented"),
        uncertain_count=sum(1 for t in teeth if t.status == "uncertain"),
        missing_count=sum(1 for t in teeth if t.status == "missing"),
        review_status=analysis.review_status,  # type: ignore[arg-type]
    )


def _nerve_of(
    row: DentalSceneRow | None,
    analysis: DentalNerveAnalysisRow | None,
) -> NerveDetectionSummary:
    """Scene-level nerve-detection summary (Phase 4): latest analysis wins.

    No persisted analysis → ``not_available`` (Phases 1–3 behaviour).
    The summary is a projection of the analysis row — counts, provider,
    review state — never client-supplied input.
    """
    if analysis is None:
        return NerveDetectionSummary(status="not_available")
    proximities = [ToothNerveProximity.model_validate(p) for p in (analysis.proximities or [])]
    return NerveDetectionSummary(
        status=analysis.detection_status,  # type: ignore[arg-type]
        input_kind=analysis.input_kind,  # type: ignore[arg-type]
        failure_code=analysis.failure_code,
        requires_review=analysis.review_status != "not_applicable",
        method=analysis.method,
        pathway_count=len(analysis.pathways or []),
        near_count=sum(1 for p in proximities if p.warning == "near"),
        watch_count=sum(1 for p in proximities if p.warning == "watch"),
        performed_at=analysis.performed_at,
        analysis_id=analysis.id,
        provider=analysis.provider,
        review_status=analysis.review_status,  # type: ignore[arg-type]
        uncertain_count=sum(
            1 for pathway in (analysis.pathways or []) if pathway.get("status") == "uncertain"
        ),
    )


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
        # CBCT series are normalized availability, not renderable meshes.
        cbct_series = [series for provision in provisions for series in provision.cbct_series]

        row = await DentalSceneService._load_row(db, clinic_id, patient_id)
        analysis = await DentalSegmentationService._latest_row(db, clinic_id, patient_id)
        nerve = await DentalNerveService._latest_row(db, clinic_id, patient_id)
        if row is None:
            return DentalSceneResponse(
                patient_id=patient_id,
                generator="intraoral_scan" if meshes else "synthetic",
                teeth=defaults,
                segmentation=_segmentation_of(None, analysis),
                nerve_detection=_nerve_of(None, nerve),
                meshes=meshes,
                cbct_series=cbct_series,
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
            segmentation=_segmentation_of(row, analysis),
            nerve_detection=_nerve_of(row, nerve),
            meshes=meshes,
            cbct_series=cbct_series,
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


class SegmentationError(Exception):
    """Application-level segmentation failures (mapped to HTTP by the router)."""


class DentalSegmentationService:
    """Segmentation use cases: run → evidence → dentist review → decision.

    ADR 0021: the service depends on the ``ToothSegmentationProvider``
    **port** only; the concrete engine (deterministic arch-partition
    today, a real ML model tomorrow) is injected by the composition
    root at the infrastructure edge. Results are persisted server-side
    with review state ``pending`` — no client-supplied analysis ever
    enters the system, and accepting a review never mutates
    odontogram records.
    """

    @staticmethod
    async def _latest_row(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> DentalSegmentationAnalysisRow | None:
        stmt = (
            select(DentalSegmentationAnalysisRow)
            .where(
                DentalSegmentationAnalysisRow.clinic_id == clinic_id,
                DentalSegmentationAnalysisRow.patient_id == patient_id,
            )
            .order_by(
                DentalSegmentationAnalysisRow.created_at.desc(),
                DentalSegmentationAnalysisRow.id.desc(),
            )
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _to_response(row: DentalSegmentationAnalysisRow) -> SegmentationAnalysisResponse:
        teeth = [SegmentedTooth.model_validate(t) for t in (row.teeth or [])]
        response = SegmentationAnalysisResponse(
            id=row.id,
            patient_id=row.patient_id,
            provider=row.provider,
            method=row.method,
            teeth=teeth,
            performed_at=row.performed_at,
            created_at=row.created_at,
            review_status=row.review_status,  # type: ignore[arg-type]
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )
        response.counts_from_teeth()
        return response

    @staticmethod
    async def run_analysis(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        provider: ToothSegmentationProvider | None = None,
        sources: list[DentalGeometrySource] | tuple[DentalGeometrySource, ...] | None = None,
    ) -> SegmentationAnalysisResponse:
        """Run the segmentation analysis for the patient's current scene.

        The tooth universe and mesh references come from the same
        geometry provisions the scene endpoint uses (odontogram-driven
        + media-discovered) — never from client input. Analysis rows
        are append-only history; the scene summary reflects the latest.
        """
        if provider is None:
            # Composition root — infrastructure edge, imported lazily.
            from .infrastructure import default_segmentation_provider

            provider = default_segmentation_provider()

        provisions = await _provisions(db, clinic_id, patient_id, sources)
        teeth = next((p.teeth for p in provisions if p.teeth), [])
        meshes = [mesh for provision in provisions for mesh in provision.meshes]

        try:
            result = await provider.segment(
                SegmentationRequest(
                    clinic_id=clinic_id,
                    patient_id=patient_id,
                    teeth=teeth,
                    meshes=meshes,
                    performed_at=datetime.now(UTC),
                )
            )
        except Exception as exc:  # provider engine failure — surface, never fake
            raise SegmentationError(f"segmentation provider failed: {exc}") from exc

        row = DentalSegmentationAnalysisRow(
            clinic_id=clinic_id,
            patient_id=patient_id,
            performed_by=user_id,
            provider=result.provider,
            method=result.method,
            performed_at=result.performed_at,
            teeth=[t.model_dump(mode="json") for t in result.teeth],
        )
        db.add(row)
        await db.commit()
        return DentalSegmentationService._to_response(row)

    @staticmethod
    async def latest_analysis(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> SegmentationAnalysisResponse | None:
        """Latest analysis for the patient, or ``None`` when never run."""
        row = await DentalSegmentationService._latest_row(db, clinic_id, patient_id)
        return None if row is None else DentalSegmentationService._to_response(row)

    @staticmethod
    async def review_analysis(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        analysis_id: UUID,
        reviewer_id: UUID | None,
        payload: SegmentationReviewUpdate,
    ) -> SegmentationAnalysisResponse:
        """Record the dentist's review decision on a pending analysis.

        Only pending analyses can be decided (409-mapped conflict on
        re-review); the decision + optional note are stored on the
        analysis row itself. Clinical data is never touched — review
        is an acknowledgement of decision support, not an odontogram
        edit.
        """
        stmt = select(DentalSegmentationAnalysisRow).where(
            DentalSegmentationAnalysisRow.id == analysis_id,
            DentalSegmentationAnalysisRow.clinic_id == clinic_id,
            DentalSegmentationAnalysisRow.patient_id == patient_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise KeyError(analysis_id)
        if row.review_status != "pending":
            raise SegmentationError("analysis already reviewed")

        row.review_status = payload.decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        row.review_note = payload.note
        await db.commit()
        return DentalSegmentationService._to_response(row)


class NerveError(Exception):
    """Application-level nerve-detection failures (mapped to HTTP by the router)."""


class DentalNerveService:
    """Nerve-detection use cases: run → evidence → dentist review → decision.

    ADR 0024: the service depends on the ``NerveDetectionProvider``
    **port** only; the concrete CBCT/model-service adapter is injected by the
    composition root at the infrastructure edge. Results are persisted
    server-side with explicit outcome and review state — no client-supplied
    detection ever enters the system, and accepting a review never
    approves an implant or surgical plan or mutates odontogram records.
    """

    @staticmethod
    async def _latest_row(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> DentalNerveAnalysisRow | None:
        stmt = (
            select(DentalNerveAnalysisRow)
            .where(
                DentalNerveAnalysisRow.clinic_id == clinic_id,
                DentalNerveAnalysisRow.patient_id == patient_id,
            )
            .order_by(
                DentalNerveAnalysisRow.created_at.desc(),
                DentalNerveAnalysisRow.id.desc(),
            )
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _to_response(row: DentalNerveAnalysisRow) -> NerveDetectionAnalysisResponse:
        pathways = [NervePathway.model_validate(p) for p in (row.pathways or [])]
        proximities = [ToothNerveProximity.model_validate(p) for p in (row.proximities or [])]
        metadata = row.analysis_metadata or {}
        response = NerveDetectionAnalysisResponse(
            id=row.id,
            patient_id=row.patient_id,
            status=row.detection_status,  # type: ignore[arg-type]
            provider=row.provider,
            method=row.method,
            input_kind=row.input_kind,  # type: ignore[arg-type]
            requires_review=row.review_status != "not_applicable",
            pathways=pathways,
            proximities=proximities,
            failure=(
                NerveDetectionFailure(
                    code=row.failure_code,
                    message=row.failure_message or "Nerve detection failed",
                )
                if row.failure_code
                else None
            ),
            provenance=(
                NerveModelProvenance.model_validate(metadata["provenance"])
                if metadata.get("provenance")
                else None
            ),
            confidence_summary=(
                NerveConfidenceSummary.model_validate(metadata["confidence_summary"])
                if metadata.get("confidence_summary")
                else None
            ),
            inference_duration_ms=metadata.get("inference_duration_ms"),
            performed_at=row.performed_at,
            created_at=row.created_at,
            review_status=row.review_status,  # type: ignore[arg-type]
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )
        response.counts_from_result()
        return response

    @staticmethod
    async def run_detection(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        provider: NerveDetectionProvider | None = None,
        requested_series_instance_uid: str | None = None,
        sources: list[DentalGeometrySource] | tuple[DentalGeometrySource, ...] | None = None,
    ) -> NerveDetectionAnalysisResponse:
        """Run the nerve-detection analysis for the patient's current scene.

        The tooth universe and mesh references come from the same
        geometry provisions the scene endpoint uses — never from client
        input. Analysis rows are append-only history; the scene summary
        reflects the latest.
        """
        if provider is None:
            # Composition root — infrastructure edge, imported lazily.
            from .infrastructure import default_nerve_provider

            provider = default_nerve_provider(db)

        provisions = await _provisions(db, clinic_id, patient_id, sources)
        teeth = next((p.teeth for p in provisions if p.teeth), [])
        meshes = [mesh for provision in provisions for mesh in provision.meshes]
        cbct_series = [series for provision in provisions for series in provision.cbct_series]

        try:
            result: NerveDetectionResult = await provider.detect(
                NerveDetectionRequest(
                    clinic_id=clinic_id,
                    patient_id=patient_id,
                    teeth=teeth,
                    meshes=meshes,
                    cbct_series=cbct_series,
                    requested_series_instance_uid=requested_series_instance_uid,
                    performed_at=datetime.now(UTC),
                )
            )
        except Exception:  # defense in depth: persist a safe failure, never leak internals
            result = NerveDetectionResult(
                status="failed",
                provider=getattr(provider, "name", "nerve-inference"),
                method="cbct-model-inference-v1",
                input_kind=getattr(provider, "input_kind", "cbct_series"),
                requires_review=False,
                failure=NerveDetectionFailure(
                    code=NerveDetectionFailureCode.INFERENCE_FAILED,
                    message="Nerve inference failed unexpectedly",
                ),
                performed_at=datetime.now(UTC),
            )

        row = DentalNerveAnalysisRow(
            clinic_id=clinic_id,
            patient_id=patient_id,
            performed_by=user_id,
            provider=result.provider,
            method=result.method,
            detection_status=result.status,
            input_kind=result.input_kind,
            failure_code=result.failure.code.value if result.failure else None,
            failure_message=result.failure.message if result.failure else None,
            analysis_metadata={
                "provenance": (
                    result.provenance.model_dump(mode="json") if result.provenance else None
                ),
                "confidence_summary": (
                    result.confidence_summary.model_dump(mode="json")
                    if result.confidence_summary
                    else None
                ),
                "inference_duration_ms": result.inference_duration_ms,
            },
            performed_at=result.performed_at,
            pathways=[p.model_dump(mode="json") for p in result.pathways],
            proximities=[p.model_dump(mode="json") for p in result.proximities],
            review_status="pending" if result.requires_review else "not_applicable",
        )
        db.add(row)
        await db.commit()
        return DentalNerveService._to_response(row)

    @staticmethod
    async def latest_analysis(
        db: AsyncSession, clinic_id: UUID, patient_id: UUID
    ) -> NerveDetectionAnalysisResponse | None:
        """Latest analysis for the patient, or ``None`` when never run."""
        row = await DentalNerveService._latest_row(db, clinic_id, patient_id)
        return None if row is None else DentalNerveService._to_response(row)

    @staticmethod
    async def review_analysis(
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        analysis_id: UUID,
        reviewer_id: UUID | None,
        payload: NerveReviewUpdate,
    ) -> NerveDetectionAnalysisResponse:
        """Record the dentist's review decision on a pending analysis.

        Only pending analyses can be decided (409-mapped conflict on
        re-review); the decision + optional note are stored on the
        analysis row itself. Clinical data is never touched and no plan
        is ever approved — review is an acknowledgement of decision
        support, not an odontogram edit.
        """
        stmt = select(DentalNerveAnalysisRow).where(
            DentalNerveAnalysisRow.id == analysis_id,
            DentalNerveAnalysisRow.clinic_id == clinic_id,
            DentalNerveAnalysisRow.patient_id == patient_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise KeyError(analysis_id)
        if row.review_status != "pending":
            raise NerveError("analysis already reviewed")

        row.review_status = payload.decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        row.review_note = payload.note
        await db.commit()
        return DentalNerveService._to_response(row)
