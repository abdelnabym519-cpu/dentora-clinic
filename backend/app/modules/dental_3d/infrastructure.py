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
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.models import Document as MediaDocument
from app.modules.odontogram.constants import DECIDUOUS_TEETH, PERMANENT_TEETH, ToothCondition
from app.modules.odontogram.models import ToothRecord

from .meshfiles import format_for_mime, mesh_download_url, mesh_mimes
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
