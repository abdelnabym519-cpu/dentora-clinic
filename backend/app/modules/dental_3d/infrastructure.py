"""Dental geometry source adapters — the infrastructure side of the port.

ADR 0020: everything that touches another module's database rows or
the outside world lives here, behind the ``DentalGeometrySource`` port
(``sources.py``). The application service depends on the port only;
this module is its composition root (``default_sources``).

Adapters:

- ``SyntheticGeometrySource`` — Phase 1 behaviour, unchanged: reads
  odontogram ``ToothRecord`` rows and synthesises the full default
  dentition. Regression-safe fallback for every future phase.
- ``IntraoralScanGeometrySource`` — Phase 2: discovers mesh documents
  (``model/stl`` / ``model/obj``) the patient already owns in the
  **media** module and describes them as scene meshes. No binary ever
  enters the scene payload — meshes are references to media documents,
  downloaded through media's own authorized route.
- ``ArchPartitionSegmentationProvider`` — Phase 3: the deterministic,
  rule-based tooth-segmentation engine behind the
  ``ToothSegmentationProvider`` port (``segmentation.py``). Explicitly
  **not** a medical AI model; replaceable by a real ML adapter in the
  composition root (``default_segmentation_provider``) without
  touching any inner contract.
- ``CanonicalMandibleNerveProvider`` — Phase 4: the deterministic
  canonical-anatomy nerve-pathway model behind the
  ``NerveDetectionProvider`` port (``nerve.py``). Explicitly **not** a
  clinically validated detector and not patient-specific anatomy;
  replaceable by a real CBCT/ML adapter in the composition root
  (``default_nerve_provider``) without touching any inner contract.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.models import Document as MediaDocument
from app.modules.odontogram.constants import DECIDUOUS_TEETH, PERMANENT_TEETH, ToothCondition
from app.modules.odontogram.models import ToothRecord

from .meshfiles import format_for_mime, mesh_download_url, mesh_mimes
from .nerve import (
    PROXIMITY_MAX_MM,
    PROXIMITY_NEAR_MM,
    PROXIMITY_WATCH_MM,
    NerveDetectionProvider,
    NerveDetectionRequest,
    NerveDetectionResult,
    NerveEvidence,
    NervePathPoint,
    NervePathway,
    NervePathwayStatus,
    ToothNerveProximity,
)
from .schemas import DentalMesh, Tooth3D
from .segmentation import (
    SegmentationAnalysisResult,
    SegmentationEvidence,
    SegmentationRequest,
    SegmentedTooth,
    ToothSegmentationProvider,
)
from .sources import DentalGeometrySource, GeometryProvision

#: Cap on real meshes surfaced per scene — bounds the payload while the
#: viewer renders one active mesh; raising it is a one-line change.
MAX_SCENE_MESHES = 8


# ---------------------------------------------------------------------------
# Synthetic source (Phase 1 behaviour behind the port)
# ---------------------------------------------------------------------------


def synthesise_teeth(records: list[ToothRecord]) -> list[Tooth3D]:
    """Build the default tooth list from odontogram records.

    Starts from the full permanent dentition so the viewer always has a
    complete arch to render, then overlays recorded conditions. Extra
    deciduous records are appended (mixed dentition support).
    """
    by_number = {r.tooth_number: r for r in records}
    teeth: list[Tooth3D] = []
    seen: set[int] = set()

    for number in PERMANENT_TEETH:
        record = by_number.get(number)
        condition = (record.general_condition if record else None) or ToothCondition.HEALTHY.value
        teeth.append(
            Tooth3D(
                tooth_number=number,
                present=condition != ToothCondition.MISSING.value,
                condition=condition,
            )
        )
        seen.add(number)

    # Deciduous records (51-85) that exist in the odontogram join as-is.
    for number, record in sorted(by_number.items()):
        if number in seen or number not in DECIDUOUS_TEETH:
            continue
        condition = record.general_condition or ToothCondition.HEALTHY.value
        teeth.append(
            Tooth3D(
                tooth_number=number,
                present=condition != ToothCondition.MISSING.value,
                condition=condition,
            )
        )

    # Stable numeric order (same as the merge path) so API consumers
    # never see two different orderings depending on persistence.
    teeth.sort(key=lambda t: t.tooth_number)
    return teeth


class SyntheticGeometrySource:
    """Phase 1's synthetic dentition, now behind the geometry port."""

    name = "synthetic"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def provide(self, clinic_id: UUID, patient_id: UUID) -> GeometryProvision:
        stmt = select(ToothRecord).where(
            ToothRecord.clinic_id == clinic_id,
            ToothRecord.patient_id == patient_id,
        )
        records = list((await self._db.execute(stmt)).scalars().all())
        return GeometryProvision(source="synthetic", teeth=synthesise_teeth(records))


# ---------------------------------------------------------------------------
# Intraoral scan source (Phase 2 — references into the media module)
# ---------------------------------------------------------------------------


def _mesh_descriptor(document: MediaDocument) -> DentalMesh:
    mesh_format = format_for_mime(document.mime_type)
    if mesh_format is None:  # pragma: no cover — query filters by mesh MIMEs
        raise ValueError(f"document {document.id} is not a mesh document")
    return DentalMesh(
        source="intraoral_scan",
        format=mesh_format,  # type: ignore[arg-type]
        document_id=document.id,
        label=document.title,
        file_size=document.file_size,
        uploaded_at=document.created_at,
        url=mesh_download_url(document.id),
    )


class IntraoralScanGeometrySource:
    """Discovers real scan meshes among the patient's media documents.

    Ownership is inherited from media: documents are filtered by
    ``clinic_id`` + ``patient_id`` + ``status='active'`` exactly like
    media's own list endpoints, so clinic isolation and archival
    semantics need no duplication here. Only documents stored with a
    canonical mesh MIME surface — arbitrary client files (PDFs,
    radiographs, …) are never mistaken for geometry.
    """

    name = "intraoral_scan"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def provide(self, clinic_id: UUID, patient_id: UUID) -> GeometryProvision:
        stmt = (
            select(MediaDocument)
            .where(
                MediaDocument.clinic_id == clinic_id,
                MediaDocument.patient_id == patient_id,
                MediaDocument.status == "active",
                MediaDocument.mime_type.in_(mesh_mimes()),
            )
            .order_by(MediaDocument.created_at.desc(), MediaDocument.id.desc())
            .limit(MAX_SCENE_MESHES)
        )
        documents = (await self._db.execute(stmt)).scalars().all()
        return GeometryProvision(
            source="intraoral_scan",
            meshes=[_mesh_descriptor(doc) for doc in documents],
        )


def default_sources(db: AsyncSession) -> list[DentalGeometrySource]:
    """Composition root: the installed geometry providers, in priority order.

    Order matters — the first source that provides teeth defines the
    default dentition (synthetic today); meshes from every source are
    aggregated. Future sources (segmentation, CBCT, face scan, Digital
    Twin) are appended here and nowhere else.
    """
    return [SyntheticGeometrySource(db), IntraoralScanGeometrySource(db)]


# ---------------------------------------------------------------------------
# Tooth segmentation provider (Phase 3 — deterministic, rule-based)
# ---------------------------------------------------------------------------


def _arch_region(tooth_number: int) -> str:
    """FDI quadrant + size category, e.g. ``Q1-molar`` (display evidence)."""
    quadrant, units = divmod(tooth_number, 10)
    if units <= 2:
        category = "incisor"
    elif units == 3:
        category = "canine"
    elif units <= 5:
        category = "premolar"
    else:
        category = "molar"
    return f"Q{quadrant}-{category}"


class ArchPartitionSegmentationProvider:
    """Deterministic arch-partition analysis — the Phase 3 engine.

    **This is not a medical AI model.** It is an explicitly rule-based
    foundation behind the :class:`ToothSegmentationProvider` port so
    the full pipeline (contracts, persistence, dentist review, UI) is
    exercisable end-to-end today; swapping in a real ML adapter later
    implements the same port and nothing else changes (ADR 0021).

    Rules (fixed, no randomness, no environment reads):

    - ``missing`` — the odontogram records the tooth as absent
      (``present=False``). Confidence 1.0 in the *status* (the record
      is the source of truth), basis ``odontogram_record``.
    - ``segmented`` — tooth present and healthy. Confidence 0.9 when
      real scan meshes back the scene (basis ``mesh_backed``), 0.75
      from the odontogram-driven synthetic arch alone (basis
      ``arch_position``). Deciduous teeth present: 0.7 — mixed
      dentition geometry is the least constrained case.
    - ``uncertain`` — tooth present but carries a restoration/finding
      condition (crown, implant, fracture, …): restorations change the
      observable geometry, so the proposal is flagged for the dentist.
      Confidence 0.5, basis ``odontogram_record``.

    Every proposal carries evidence (arch region, backing document
    ids, rule note). The schema pins ``is_clinical=False`` and
    ``requires_review=True`` — this provider cannot claim otherwise.
    """

    name = "arch-partition"
    input_kind = "scene"  # type: ignore[assignment]  # literal matches the port

    async def segment(self, request: SegmentationRequest) -> SegmentationAnalysisResult:
        backing = [m.document_id for m in request.meshes if m.document_id is not None]
        teeth: list[SegmentedTooth] = []

        for tooth in request.teeth:
            region = _arch_region(tooth.tooth_number)
            if not tooth.present:
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="missing",
                        confidence=1.0,
                        evidence=SegmentationEvidence(
                            basis="odontogram_record",
                            arch_region=region,
                            note="odontogram ToothRecord marks the tooth absent",
                        ),
                    )
                )
                continue

            deciduous = tooth.tooth_number >= 51
            if tooth.condition != "healthy":
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="uncertain",
                        confidence=0.5,
                        evidence=SegmentationEvidence(
                            basis="odontogram_record",
                            arch_region=region,
                            backing_documents=backing,
                            note=f"recorded condition '{tooth.condition}' alters geometry",
                        ),
                    )
                )
            elif backing:
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="segmented",
                        confidence=0.9,
                        evidence=SegmentationEvidence(
                            basis="mesh_backed",
                            arch_region=region,
                            backing_documents=backing,
                            note="arch position backed by real scan geometry",
                        ),
                    )
                )
            else:
                teeth.append(
                    SegmentedTooth(
                        tooth_number=tooth.tooth_number,
                        status="segmented",
                        confidence=0.7 if deciduous else 0.75,
                        evidence=SegmentationEvidence(
                            basis="arch_position",
                            arch_region=region,
                            note="synthetic arch partition (no scan geometry yet)",
                        ),
                    )
                )

        teeth.sort(key=lambda t: t.tooth_number)
        return SegmentationAnalysisResult(
            provider=self.name,
            method="deterministic-arch-partition-v0",
            teeth=teeth,
            performed_at=request.performed_at,
        )


def default_segmentation_provider() -> ToothSegmentationProvider:
    """Composition root for segmentation — the installed engine.

    Replacing the rule-based analysis with a real ML model means
    returning a different ``ToothSegmentationProvider`` here (and only
    here); the service, contracts, persistence and UI are untouched.
    """
    return ArchPartitionSegmentationProvider()


# ---------------------------------------------------------------------------
# Phase 4 — mandibular nerve detection (deterministic canonical model)
# ---------------------------------------------------------------------------

#: Canonical arch frame — mirrors ``frontend/lib/dentalArch.ts`` exactly
#: (half-width 2.2, depth 1.5, gap 0.5, lower arch at y = -0.25) so the
#: backend pathway and the viewer's synthetic arch share one coordinate
#: system. Any drift between the two files is a bug in one of them.
NERVE_ARCH_HALF_WIDTH = 2.2
NERVE_ARCH_DEPTH = 1.5
NERVE_ARCH_GAP = 0.5

#: Root apex offset below a lower tooth's centroid (the synthetic root
#: cone hangs ~0.45 below the occlusal centroid — viewer buildToothMeshes).
NERVE_APEX_DROP = 0.45

#: Demo-model millimetre scale. The canonical frame is unit-less; a
#: mandibular half-width of 2.2 units ≈ 22 mm gives plausible model-space
#: proximities. **Not a calibration** — the whole model is explicitly a
#: non-clinical demo (ADR 0022).
NERVE_MM_PER_UNIT = 10.0

#: Lower permanent arch, molar→molar, exactly as the viewer lays it out
#: (``Dental3DViewer`` default ``lowerOrder``).
_LOWER_ORDER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

#: Mandibular-canal polyline control points per side, in the canonical
#: frame. ``s`` is the side sign: +1 = patient left (+x), -1 = right.
#: Shape: canal entry at the ramus behind the third molar, dipping under
#: the molar roots, then rising and curving medially to the mental
#: foramen between the premolar apices. Canonical demo anatomy — never
#: patient-measured data (ADR 0022).
_CANAL_POINTS: tuple[tuple[float, float, float], ...] = (
    (2.65, -0.98, -1.85),
    (2.30, -0.84, -1.52),
    (2.02, -0.78, -1.02),
    (1.75, -0.75, -0.55),
    (1.35, -0.70, -0.12),
    (1.18, -0.68, 0.08),
)


def _lower_apex(fdi: int) -> tuple[float, float, float] | None:
    """Root-apex position of a lower permanent tooth in the arch frame.

    Mirrors ``layoutArch`` (``dentalArch.ts``): t ∈ [-1, 1] across the
    16-tooth lower order, x = ±2.2·t, z = -1.5·t², then dropped to the
    apex. Returns ``None`` for non-lower teeth.
    """
    try:
        index = _LOWER_ORDER.index(fdi)
    except ValueError:
        return None
    t = (index / (len(_LOWER_ORDER) - 1)) * 2 - 1
    return (
        t * NERVE_ARCH_HALF_WIDTH,
        -NERVE_ARCH_GAP / 2 - NERVE_APEX_DROP,
        -NERVE_ARCH_DEPTH * t * t,
    )


def _point_segment_distance(
    p: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> float:
    """Euclidean distance from point ``p`` to segment ``ab``."""
    ax, ay, az = a
    bx, by, bz = b
    px, py, pz = p
    ab = (bx - ax, by - ay, bz - az)
    ap = (px - ax, py - ay, pz - az)
    denom = ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2
    t = (
        0.0
        if denom == 0
        else max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / denom))
    )
    dx = ap[0] - t * ab[0]
    dy = ap[1] - t * ab[1]
    dz = ap[2] - t * ab[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def _closest_on_pathway(
    apex: tuple[float, float, float], points: list[tuple[float, float, float]]
) -> tuple[float, int]:
    """(min distance in units, index of the closest polyline vertex)."""
    best_distance = float("inf")
    best_index = 0
    for i in range(len(points) - 1):
        d = _point_segment_distance(apex, points[i], points[i + 1])
        if d < best_distance:
            d_to_a = _point_segment_distance(apex, points[i], points[i])
            d_to_b = _point_segment_distance(apex, points[i + 1], points[i + 1])
            best_index = i if d_to_a <= d_to_b else i + 1
            best_distance = d
    return best_distance, best_index


def _warning_band(distance_mm: float) -> str:
    """Planning-support band — never a clinical safety verdict."""
    if distance_mm < PROXIMITY_NEAR_MM:
        return "near"
    if distance_mm < PROXIMITY_WATCH_MM:
        return "watch"
    return "none"


class CanonicalMandibleNerveProvider:
    """Deterministic canonical-mandible model — the Phase 4 engine.

    **This is not a medical AI model and not patient-specific anatomy.**
    It derives left/right mandibular-canal pathway polylines from a
    fixed canonical model (documented constants in the viewer's arch
    frame) and computes AI-estimated proximities from the odontogram's
    lower-tooth positions, so the full pipeline (contracts, persistence,
    dentist review, 3D overlay) is exercisable end-to-end today.
    Swapping in a real CBCT/ML detector later implements the same
    :class:`NerveDetectionProvider` port and nothing else changes
    (ADR 0022).

    Rules (fixed, no randomness, no environment reads):

    - One pathway per side (left/right), polyline of 6 canonical points.
    - ``status`` — ``uncertain`` (confidence 0.6) when the scene has no
      real geometry at all: the pathway is then purely generic model
      geometry; ``detected`` (confidence 0.75) when scan meshes back
      the arch frame. Even then the pathway itself remains canonical —
      confidence is capped at 0.75 because no patient canal was
      segmented; basis stays ``anatomical_model``.
    - ``proximities`` — present permanent lower teeth (FDI 41–48, 31–38)
      only; distance = min point-to-polyline distance from the tooth's
      root-apex anchor, scaled by ``NERVE_MM_PER_UNIT``; teeth farther
      than ``PROXIMITY_MAX_MM`` are omitted; bands near/watch/none are
      display bands, never clinical verdicts.

    Every pathway carries evidence. The schema pins
    ``is_clinical=False`` and ``requires_review=True`` — this provider
    cannot claim otherwise, and no tooth is ever labelled clinically
    unsafe.
    """

    name = "canonical-mandible"
    input_kind = "scene"  # type: ignore[assignment]  # literal matches the port

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
        backing = [m.document_id for m in request.meshes if m.document_id is not None]
        confidence = 0.75 if backing else 0.6
        status: NervePathwayStatus = "detected" if backing else "uncertain"
        note = (
            "canonical mandibular canal model over scan-backed arch frame"
            if backing
            else "canonical mandibular canal model (demo) — no patient geometry yet"
        )

        pathways: list[NervePathway] = []
        for side, sign in (("left", 1.0), ("right", -1.0)):
            points = [(sign * x, y, z) for x, y, z in _CANAL_POINTS]
            pathways.append(
                NervePathway(
                    side=side,
                    region="mandibular_canal",
                    source="canonical_demo_model",
                    status=status,
                    confidence=confidence,
                    points=[NervePathPoint(x=x, y=y, z=z) for x, y, z in points],
                    evidence=NerveEvidence(
                        basis="anatomical_model",
                        note=note,
                        backing_documents=backing,
                    ),
                )
            )

        by_side = {"left": pathways[0], "right": pathways[1]}
        proximities: list[ToothNerveProximity] = []
        for tooth in sorted(request.teeth, key=lambda t: t.tooth_number):
            if not tooth.present:
                continue
            quadrant = tooth.tooth_number // 10
            if quadrant not in (3, 4):
                continue  # canal model relates to the permanent lower arch
            side = "left" if quadrant == 3 else "right"
            apex = _lower_apex(tooth.tooth_number)
            if apex is None:  # pragma: no cover — order covers 31–48
                continue
            sign = 1.0 if side == "left" else -1.0
            raw_points = [(sign * x, y, z) for x, y, z in _CANAL_POINTS]
            units, vertex = _closest_on_pathway(apex, raw_points)
            distance_mm = round(units * NERVE_MM_PER_UNIT, 2)
            if distance_mm > PROXIMITY_MAX_MM:
                continue
            proximities.append(
                ToothNerveProximity(
                    tooth_number=tooth.tooth_number,
                    side=side,  # type: ignore[arg-type]
                    distance_mm=distance_mm,
                    closest_point_index=vertex,
                    warning=_warning_band(distance_mm),  # type: ignore[arg-type]
                    confidence=by_side[side].confidence,
                )
            )

        return NerveDetectionResult(
            provider=self.name,
            method="canonical-mandible-model-v0",
            pathways=pathways,
            proximities=proximities,
            performed_at=request.performed_at,
        )


def default_nerve_provider() -> NerveDetectionProvider:
    """Composition root for nerve detection — the installed engine.

    Replacing the canonical demo model with a real CBCT/ML detector
    means returning a different ``NerveDetectionProvider`` here (and
    only here); the service, contracts, persistence and UI are
    untouched.
    """
    return CanonicalMandibleNerveProvider()
