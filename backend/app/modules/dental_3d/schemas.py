"""Dental 3D domain contracts (Phase 2 — real mesh references).

These Pydantic models are the wire + persistence contract for a dental
3D scene. They are deliberately source-agnostic: every tooth references
a :class:`DentalMesh` descriptor whose ``source`` says where the
geometry comes from. Phase 1 produced ``synthetic`` procedural geometry
only; Phase 2 additionally surfaces real intraoral-scan meshes at scene
level as **references** to media documents (STL / OBJ). The remaining
sources are reserved for future phases so they can be dropped in
without touching the API shape:

- ``segmentation`` — automatic tooth-segmentation meshes (future)
- ``cbct`` — CBCT-derived meshes (future)
- ``face_scan`` — 3D face scans (future)
- ``digital_twin`` — Dental Digital Twin components (future)

Geometry providers implement the ``DentalGeometrySource`` port
(``sources.py``); none of those future capabilities exist yet and no
code path may set their sources.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.odontogram.constants import ALL_TEETH

#: Provenance of the geometry behind a mesh descriptor.
MeshSource = Literal[
    "synthetic",
    "segmentation",
    "cbct",
    "intraoral_scan",
    "face_scan",
    "digital_twin",
]

#: How the geometry is delivered to the viewer.
MeshFormat = Literal["procedural", "stl", "obj", "gltf"]

SegmentationStatus = Literal["not_available", "synthetic", "completed"]


def _is_valid_fdi(tooth_number: int) -> bool:
    """True for a permanent (11–48) or deciduous (51–85) FDI number."""
    return tooth_number in ALL_TEETH


class DentalMesh(BaseModel):
    """Geometry descriptor for one dental object.

    Phase 1 teeth always use ``source="synthetic"``, ``format="procedural"``
    and no ``document_id`` — the viewer generates the shape locally.
    Phase 2 adds real surface meshes at scene level
    (``source="intraoral_scan"``): ``format`` selects the container
    (``stl`` / ``obj``), ``document_id`` references the file stored
    through the existing **media** module and ``url`` points at media's
    authorized download route. No binary ever enters the scene payload
    — meshes are references. ``label`` / ``file_size`` /
    ``uploaded_at`` are display metadata mirrored from the document.
    """

    source: MeshSource = "synthetic"
    format: MeshFormat = "procedural"
    document_id: UUID | None = None
    vertex_count: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=255)
    file_size: int | None = Field(default=None, ge=0)
    uploaded_at: datetime | None = None
    #: Content URL (media download route) — set by the server only.
    url: str | None = Field(default=None, max_length=500)


class Tooth3D(BaseModel):
    """One tooth inside a :class:`DentalScene`.

    ``tooth_number`` is FDI notation (the odontogram is the source of
    truth for tooth identity — never duplicated here). ``condition``
    mirrors ``ToothRecord.general_condition`` when synthesised from the
    odontogram; the viewer derives the render colour from it unless a
    ``color`` override (``#RRGGBB``) is set.
    """

    tooth_number: int = Field(description="FDI notation (permanent 11-48, deciduous 51-85)")
    present: bool = True
    condition: str = "healthy"
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    visible: bool = True
    mesh: DentalMesh = Field(default_factory=DentalMesh)

    @field_validator("tooth_number")
    @classmethod
    def _valid_fdi(cls, value: int) -> int:
        if not _is_valid_fdi(value):
            raise ValueError(f"{value} is not a valid FDI tooth number")
        return value


class SegmentationResult(BaseModel):
    """Placeholder contract for automatic tooth segmentation.

    Phase 1 never produces a segmentation. The field exists so a future
    phase can attach results to the scene without a schema break. While
    segmentation does not exist the service always reports
    ``status="not_available"``.
    """

    status: SegmentationStatus = "not_available"
    method: str | None = None
    teeth_found: int = Field(default=0, ge=0)
    performed_at: datetime | None = None


class DentalScene(BaseModel):
    """Full scene for one patient — the aggregate root of the contract."""

    generator: Literal[
        "synthetic", "segmentation", "cbct", "intraoral_scan", "face_scan", "digital_twin"
    ] = "synthetic"
    teeth: list[Tooth3D] = Field(default_factory=list, max_length=52)
    segmentation: SegmentationResult = Field(default_factory=SegmentationResult)
    #: Real surface meshes (Phase 2: intraoral scan references).
    #: Server-derived — never accepted from clients.
    meshes: list[DentalMesh] = Field(default_factory=list, max_length=16)


class DentalSceneResponse(BaseModel):
    """API payload returned by GET/PUT — scene plus persistence metadata."""

    id: UUID | None = None
    patient_id: UUID
    generator: str
    teeth: list[Tooth3D]
    segmentation: SegmentationResult
    meshes: list[DentalMesh] = Field(default_factory=list)
    updated_at: datetime | None = None
    persisted: bool = False


class DentalSceneUpdate(BaseModel):
    """Full-replace payload for PUT — per-tooth view state only.

    ``segmentation`` is accepted (round-trip) but rejected unless it is
    the Phase 1 placeholder; producing segmentation results is a future
    capability and must not be client-supplied. Real meshes are
    **server-derived** (media documents), so the payload has no
    ``meshes`` field and any tooth-level mesh reference injected by a
    client is rejected — view state only.
    """

    teeth: list[Tooth3D] = Field(max_length=52)
    segmentation: SegmentationResult | None = None

    @field_validator("segmentation")
    @classmethod
    def _no_segmentation_yet(cls, value: SegmentationResult | None) -> SegmentationResult | None:
        if value is not None and value.status == "completed":
            raise ValueError("segmentation results cannot be supplied — capability not available")
        return value

    @field_validator("teeth")
    @classmethod
    def _teeth_meshes_are_view_state_only(cls, value: list[Tooth3D]) -> list[Tooth3D]:
        for tooth in value:
            mesh = tooth.mesh
            if (
                mesh.source != "synthetic"
                or mesh.format != "procedural"
                or mesh.document_id is not None
            ):
                raise ValueError(
                    "tooth mesh descriptors are server-derived — PUT accepts only "
                    "the default synthetic mesh"
                )
        return value
