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
