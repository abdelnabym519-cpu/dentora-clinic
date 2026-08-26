"""Dental geometry sources — the application/domain boundary port.

ADR 0019 / ADR 0020: whenever a use case needs an external capability it
must depend on an **interface defined at the inner boundary**, never on
the concrete infrastructure behind it. Dental geometry is exactly such
a capability: Phase 1 synthesises it from odontogram state; Phase 2 adds
intraoral scan meshes discovered from the **media** module; Phase 5.1 adds
normalized CBCT/DICOM series availability without pretending that a volume is
a renderable mesh. Future geometry adapters implement the same port:

    Application use case (service.py)
            ↓ depends on
    DentalGeometrySource            ← this file (inner layer)
            ↑ implemented by
    infrastructure.py adapters      (SQLAlchemy, media, future AI)

This file must stay framework-free: no FastAPI, no SQLAlchemy, no
media imports, no storage, no HTTP — only the neutral contracts from
``.schemas``. Adapters live in ``.infrastructure``; the composition
root (``default_sources``) lives there too so the inner layers never
import outward.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field

from .cbct import CbctSeriesDescriptor
from .schemas import DentalMesh, MeshSource, Tooth3D


class GeometryProvision(BaseModel):
    """What one geometry source contributes to a patient's scene.

    A provision is intentionally partial: the synthetic source provides
    ``teeth``; intraoral scan provides surface ``meshes``; CBCT provides
    normalized ``cbct_series`` availability. The service aggregates them and
    never asks which parser/storage implementation produced the data.
    """

    source: MeshSource
    teeth: list[Tooth3D] = Field(default_factory=list, max_length=52)
    meshes: list[DentalMesh] = Field(default_factory=list, max_length=16)
    cbct_series: list[CbctSeriesDescriptor] = Field(default_factory=list, max_length=32)


@runtime_checkable
class DentalGeometrySource(Protocol):
    """Port: dental geometry for one patient, regardless of origin.

    Implementations are session-scoped (constructed with the request's
    ``AsyncSession`` by the composition root) and must filter every
    query by ``clinic_id`` — clinic isolation is part of the contract,
    not an afterthought. ``name`` is a stable identifier for logging
    and future per-source configuration.
    """

    name: str

    async def provide(self, clinic_id: UUID, patient_id: UUID) -> GeometryProvision:
        """Return this source's contribution to the patient's scene."""
        ...
