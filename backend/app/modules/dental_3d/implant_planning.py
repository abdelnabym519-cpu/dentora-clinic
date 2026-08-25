"""Deterministic patient-space implant planning contracts and geometry.

This module contains framework-independent engineering decision-support rules.
It never invents clinical thresholds, does not choose an implant autonomously,
and persists/returns geometry only in DICOM patient millimetres.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal
from uuid import UUID

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scipy.optimize import minimize_scalar

from .registration import Point3D

PlanStatus = Literal["draft", "proposed", "accepted", "rejected"]
ReviewStatus = Literal["pending_review", "accepted", "rejected"]
ProstheticSourceType = Literal[
    "dentist_defined", "registered_ios", "prosthetic_scan", "prosthetic_design"
]
CheckStatus = Literal["AVAILABLE", "UNAVAILABLE"]
SortDirection = Literal["asc", "desc"]
PlanningCriterionName = Literal[
    "prosthetic_offset_mm",
    "prosthetic_axis_angle_deg",
    "nerve_surface_to_centerline_mm",
    "diameter_mm",
    "length_mm",
]

NERVE_DISTANCE_SEMANTICS = "implant_surface_to_mandibular_canal_centerline"
NO_CLINICAL_THRESHOLD = "NO_CLINICAL_THRESHOLD_DEFINED"


class UnitVector3D(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def _is_normalized(self) -> UnitVector3D:
        norm = math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)
        if abs(norm - 1.0) > 1e-6:
            raise ValueError("axis must be normalized")
        return self


class ImplantCatalogEntry(BaseModel):
    """Explicit implant dimensions with traceable provenance."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)
    diameter_mm: float = Field(gt=0, le=20)
    length_mm: float = Field(gt=0, le=50)
    dimension_source: str = Field(min_length=1, max_length=255)
    source_identifier: str | None = Field(default=None, max_length=255)


class ImplantCandidate(BaseModel):
    """A finite parametric implant cylinder in DICOM patient space."""

    model_config = ConfigDict(extra="forbid")

    center: Point3D
    axis: UnitVector3D
    diameter_mm: float = Field(gt=0, le=20)
    length_mm: float = Field(gt=0, le=50)
    frame_of_reference_uid: str = Field(min_length=1, max_length=64)
    unit: Literal["mm"] = "mm"
    catalog_entry_id: str | None = Field(default=None, max_length=100)
    dimension_source: str = Field(min_length=1, max_length=255)


class ProstheticTargetCreate(BaseModel):
    """Explicit prosthetic target; never inferred from anatomy or a candidate."""

    model_config = ConfigDict(extra="forbid")

    alignment_id: UUID
    platform_center: Point3D
    axis: UnitVector3D
    frame_of_reference_uid: str = Field(min_length=1, max_length=64)
    source_type: ProstheticSourceType
    source_reference_space: Literal["ios_mesh", "dicom_patient"]
    source_frame_of_reference_uid: str | None = Field(default=None, max_length=64)
    source_method: str = Field(min_length=1, max_length=100)
    source_identifier: str = Field(min_length=1, max_length=255)
    source_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    source_document_ids: list[UUID] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def _real_sources_have_provenance(self) -> ProstheticTargetCreate:
        if self.source_type != "dentist_defined":
            if self.source_digest is None or not self.source_document_ids:
                raise ValueError("real IOS/prosthetic targets require digest and source documents")
        if self.source_type == "registered_ios" and self.source_reference_space != "ios_mesh":
            raise ValueError("registered_ios target must declare ios_mesh source coordinates")
        if self.source_reference_space == "dicom_patient":
            if self.source_frame_of_reference_uid != self.frame_of_reference_uid:
                raise ValueError("DICOM prosthetic source must match the target patient frame")
        elif self.source_frame_of_reference_uid is not None:
            raise ValueError("IOS source cannot claim a DICOM Frame of Reference UID")
        return self


class ProstheticTargetResponse(ProstheticTargetCreate):
    id: UUID
    patient_id: UUID
    review_status: ReviewStatus
    created_by: UUID | None = None
    created_at: datetime | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=1000)


class ProstheticTargetReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=1000)


class ProstheticPlanning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "unavailable"]
    target: ProstheticTargetResponse | None = None
    reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _coherent(self) -> ProstheticPlanning:
        if self.status == "available":
            if self.target is None or self.target.review_status != "accepted":
                raise ValueError("available prosthetic planning requires accepted target")
        elif self.target is not None:
            raise ValueError("unavailable prosthetic planning cannot expose a target")
        return self


class PlanningCheck(BaseModel):
    """Measured fact or explicit unavailable state; never a hidden verdict."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: CheckStatus
    value: float | None = None
    unit: str | None = Field(default=None, max_length=32)
    semantics: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def _coherent(self) -> PlanningCheck:
        if self.status == "AVAILABLE" and self.value is None:
            raise ValueError("available check requires a value")
        if self.status == "UNAVAILABLE" and self.value is not None:
            raise ValueError("unavailable check cannot fabricate a value")
        return self


class ImplantAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prosthetic_offset_mm: PlanningCheck
    prosthetic_axis_angle_deg: PlanningCheck
    nerve_surface_to_centerline_mm: PlanningCheck
    bone_axis_span_mm: PlanningCheck
    bone_width_1_mm: PlanningCheck
    bone_width_2_mm: PlanningCheck
    bone_contained_fraction: PlanningCheck
    bone_contained_volume_mm3: PlanningCheck
    intersects_nerve_centerline: bool | None = None
    clinical_threshold_status: Literal["NO_CLINICAL_THRESHOLD_DEFINED"] = NO_CLINICAL_THRESHOLD


class PlanningCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_of_reference_uid: str = Field(min_length=1, max_length=64)
    alignment_id: UUID
    prosthetic_target_id: UUID | None = None
    prosthetic_status: Literal["accepted", "unavailable"]
    nerve_analysis_id: UUID | None = None
    bone_volume_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"


class PlanningCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: PlanningCriterionName
    direction: SortDirection


class PlanningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[PlanningCriterion] = Field(min_length=1, max_length=5)

    @field_validator("criteria")
    @classmethod
    def _unique_criteria(cls, value: list[PlanningCriterion]) -> list[PlanningCriterion]:
        names = [criterion.name for criterion in value]
        if len(names) != len(set(names)):
            raise ValueError("planning criteria must be unique")
        return value


class ImplantPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: ImplantCandidate


class ImplantPlanEdit(ImplantPlanCreate):
    pass


class ImplantPlanReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=1000)


class ImplantPlanRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    plan_id: UUID
    revision_number: int = Field(ge=1)
    candidate: ImplantCandidate
    assessment: ImplantAssessment
    planning_case: PlanningCase
    policy: PlanningPolicy | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None


class DentalImplantPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    patient_id: UUID
    status: PlanStatus
    current_revision: ImplantPlanRevisionResponse
    created_by: UUID | None = None
    created_at: datetime | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=1000)
    requires_review: Literal[True] = True
    is_clinical: Literal[False] = False
    disclaimer: Literal[
        "Engineering implant-planning decision support only; dentist approval is required."
    ] = "Engineering implant-planning decision support only; dentist approval is required."


class ImplantProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog: list[ImplantCatalogEntry] = Field(min_length=1, max_length=100)
    policy: PlanningPolicy


class ImplantPlanningSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prosthetic: ProstheticPlanning
    latest_target: ProstheticTargetResponse | None = None
    plans: list[DentalImplantPlanResponse] = Field(default_factory=list)


def _arr(point: Point3D | UnitVector3D) -> np.ndarray:
    return np.array([point.x, point.y, point.z], dtype=float)


def _point(values: np.ndarray) -> Point3D:
    return Point3D(x=float(values[0]), y=float(values[1]), z=float(values[2]))


def platform_point(candidate: ImplantCandidate) -> Point3D:
    """Return the implant platform center from center + platform→apex axis."""

    return _point(_arr(candidate.center) - _arr(candidate.axis) * (candidate.length_mm * 0.5))


def candidate_from_target(
    target: ProstheticTargetResponse,
    entry: ImplantCatalogEntry,
) -> ImplantCandidate:
    """Build a prosthetic-guided candidate deterministically."""

    center = _arr(target.platform_center) + _arr(target.axis) * (entry.length_mm * 0.5)
    return ImplantCandidate(
        center=_point(center),
        axis=target.axis,
        diameter_mm=entry.diameter_mm,
        length_mm=entry.length_mm,
        frame_of_reference_uid=target.frame_of_reference_uid,
        catalog_entry_id=entry.id,
        dimension_source=entry.dimension_source,
    )


def parametric_implant_mesh(candidate: ImplantCandidate, sections: int = 32) -> trimesh.Trimesh:
    """Create display/engineering mesh from explicit dimensions, never vendor CAD."""

    axis = _arr(candidate.axis)
    transform = trimesh.geometry.align_vectors([0.0, 0.0, 1.0], axis)
    if transform is None:
        transform = np.eye(4)
    transform = np.asarray(transform, dtype=float)
    transform[:3, 3] = _arr(candidate.center)
    return trimesh.creation.cylinder(
        radius=candidate.diameter_mm * 0.5,
        height=candidate.length_mm,
        sections=sections,
        transform=transform,
    )


def _available(value: float, unit: str, semantics: str) -> PlanningCheck:
    return PlanningCheck(status="AVAILABLE", value=float(value), unit=unit, semantics=semantics)


def unavailable(semantics: str, unit: str | None = None) -> PlanningCheck:
    return PlanningCheck(status="UNAVAILABLE", value=None, unit=unit, semantics=semantics)


def prosthetic_measurements(
    candidate: ImplantCandidate,
    target: ProstheticTargetResponse | None,
) -> tuple[PlanningCheck, PlanningCheck]:
    if target is None:
        return (
            unavailable("prosthetic_platform_offset", "mm"),
            unavailable("directed_prosthetic_axis_angle", "deg"),
        )
    if target.frame_of_reference_uid != candidate.frame_of_reference_uid:
        raise ValueError("prosthetic target and implant candidate must share one patient frame")
    offset = float(np.linalg.norm(_arr(platform_point(candidate)) - _arr(target.platform_center)))
    dot = float(np.clip(np.dot(_arr(candidate.axis), _arr(target.axis)), -1.0, 1.0))
    angle = math.degrees(math.acos(dot))
    return (
        _available(offset, "mm", "prosthetic_platform_offset"),
        _available(angle, "deg", "directed_prosthetic_axis_angle"),
    )


def _point_to_finite_cylinder_solid(
    point: np.ndarray,
    candidate: ImplantCandidate,
) -> float:
    center = _arr(candidate.center)
    axis = _arr(candidate.axis)
    half = candidate.length_mm * 0.5
    radius = candidate.diameter_mm * 0.5
    rel = point - center
    axial = float(np.dot(rel, axis))
    radial_vec = rel - axis * axial
    radial = float(np.linalg.norm(radial_vec))
    dz = abs(axial) - half
    dr = radial - radius
    if dz <= 0 and dr <= 0:
        return 0.0
    if dz <= 0:
        return max(dr, 0.0)
    if dr <= 0:
        return max(dz, 0.0)
    return math.hypot(dz, dr)


def point_to_implant_surface_mm(point: Point3D, candidate: ImplantCandidate) -> float:
    """Non-negative distance from a point to the finite implant solid."""

    return _point_to_finite_cylinder_solid(_arr(point), candidate)


def _segment_to_implant_surface_mm(
    start: np.ndarray,
    end: np.ndarray,
    candidate: ImplantCandidate,
) -> float:
    delta = end - start
    if float(np.linalg.norm(delta)) == 0.0:
        return _point_to_finite_cylinder_solid(start, candidate)

    result = minimize_scalar(
        lambda t: _point_to_finite_cylinder_solid(start + delta * float(t), candidate),
        bounds=(0.0, 1.0),
        method="bounded",
        options={"xatol": 1e-10, "maxiter": 200},
    )
    endpoint = min(
        _point_to_finite_cylinder_solid(start, candidate),
        _point_to_finite_cylinder_solid(end, candidate),
    )
    distance = min(float(result.fun), endpoint)
    return 0.0 if distance < 1e-7 else distance


def nerve_surface_distance_mm(
    candidate: ImplantCandidate,
    pathways: list[list[Point3D]],
) -> tuple[PlanningCheck, bool | None]:
    """Shortest implant-solid to accepted nerve-centerline distance.

    The result is intentionally *not* called canal-wall clearance: the
    upstream nerve contract contains a centerline only, not a validated
    canal-wall radius/surface.
    """

    usable = [points for points in pathways if len(points) >= 2]
    if not usable:
        return unavailable(NERVE_DISTANCE_SEMANTICS, "mm"), None

    best = math.inf
    for points in usable:
        for start, end in zip(points, points[1:], strict=False):
            best = min(
                best,
                _segment_to_implant_surface_mm(_arr(start), _arr(end), candidate),
            )
    if not math.isfinite(best):
        return unavailable(NERVE_DISTANCE_SEMANTICS, "mm"), None
    return _available(best, "mm", NERVE_DISTANCE_SEMANTICS), best == 0.0


def unavailable_bone_checks() -> tuple[
    PlanningCheck, PlanningCheck, PlanningCheck, PlanningCheck, PlanningCheck
]:
    """Default runtime boundary: no persisted validated bone volume exists yet."""

    return (
        unavailable("validated_segmented_bone_axis_span", "mm"),
        unavailable("validated_segmented_bone_width_orthogonal_1", "mm"),
        unavailable("validated_segmented_bone_width_orthogonal_2", "mm"),
        unavailable("implant_volume_fraction_inside_validated_bone", "ratio"),
        unavailable("implant_volume_inside_validated_bone", "mm3"),
    )


def assess_candidate(
    candidate: ImplantCandidate,
    *,
    target: ProstheticTargetResponse | None,
    nerve_pathways: list[list[Point3D]],
) -> ImplantAssessment:
    platform_offset, axis_angle = prosthetic_measurements(candidate, target)
    nerve_distance, intersects = nerve_surface_distance_mm(candidate, nerve_pathways)
    axis_span, width_1, width_2, fraction, volume = unavailable_bone_checks()
    return ImplantAssessment(
        prosthetic_offset_mm=platform_offset,
        prosthetic_axis_angle_deg=axis_angle,
        nerve_surface_to_centerline_mm=nerve_distance,
        bone_axis_span_mm=axis_span,
        bone_width_1_mm=width_1,
        bone_width_2_mm=width_2,
        bone_contained_fraction=fraction,
        bone_contained_volume_mm3=volume,
        intersects_nerve_centerline=intersects,
    )


def _criterion_value(
    candidate: ImplantCandidate,
    assessment: ImplantAssessment,
    name: PlanningCriterionName,
) -> float | None:
    if name == "diameter_mm":
        return candidate.diameter_mm
    if name == "length_mm":
        return candidate.length_mm
    check = {
        "prosthetic_offset_mm": assessment.prosthetic_offset_mm,
        "prosthetic_axis_angle_deg": assessment.prosthetic_axis_angle_deg,
        "nerve_surface_to_centerline_mm": assessment.nerve_surface_to_centerline_mm,
    }[name]
    return check.value if check.status == "AVAILABLE" else None


def rank_candidates(
    candidates: list[tuple[ImplantCandidate, ImplantAssessment]],
    policy: PlanningPolicy,
) -> list[tuple[ImplantCandidate, ImplantAssessment]]:
    """Deterministic ordering from caller-supplied criteria only.

    Missing measurements sort after available measurements for that criterion,
    then stable catalog id/dimensions break complete ties for reproducibility.
    """

    def key(item: tuple[ImplantCandidate, ImplantAssessment]) -> tuple:
        candidate, assessment = item
        parts: list[tuple[int, float]] = []
        for criterion in policy.criteria:
            value = _criterion_value(candidate, assessment, criterion.name)
            if value is None:
                parts.append((1, 0.0))
            else:
                parts.append((0, value if criterion.direction == "asc" else -value))
        return (
            *parts,
            candidate.catalog_entry_id or "",
            candidate.diameter_mm,
            candidate.length_mm,
        )

    return sorted(candidates, key=key)


__all__ = [
    "DentalImplantPlanResponse",
    "ImplantAssessment",
    "ImplantCandidate",
    "ImplantCatalogEntry",
    "ImplantPlanCreate",
    "ImplantPlanEdit",
    "ImplantPlanReviewUpdate",
    "ImplantPlanRevisionResponse",
    "ImplantPlanningSnapshot",
    "ImplantProposalRequest",
    "PlanningCase",
    "PlanningCheck",
    "PlanningCriterion",
    "PlanningPolicy",
    "ProstheticPlanning",
    "ProstheticTargetCreate",
    "ProstheticTargetResponse",
    "ProstheticTargetReviewUpdate",
    "UnitVector3D",
    "assess_candidate",
    "candidate_from_target",
    "nerve_surface_distance_mm",
    "parametric_implant_mesh",
    "platform_point",
    "point_to_implant_surface_mm",
    "rank_candidates",
    "unavailable",
]
