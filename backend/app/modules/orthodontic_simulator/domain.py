"""Deterministic orthodontic-simulation domain.

This module contains no database, network, AI, model-runtime or storage code.
The movement/staging concepts are adapted from OpenSource Ortho (Apache-2.0),
while Dentora owns this integration contract and its stricter fail-closed rules.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from math import ceil, hypot
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Arch(StrEnum):
    MAXILLARY = "maxillary"
    MANDIBULAR = "mandibular"


class FdiToothId(BaseModel):
    """Canonical two-digit FDI identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str = Field(min_length=2, max_length=2)
    system: Literal["FDI"] = "FDI"

    @field_validator("value")
    @classmethod
    def _valid_fdi(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("FDI tooth id must contain exactly two digits")
        quadrant, position = value
        if quadrant not in "12345678" or position not in "12345678":
            raise ValueError("FDI quadrant and position must each be in 1..8")
        return value

    @property
    def arch(self) -> Arch:
        return Arch.MAXILLARY if self.value[0] in "1256" else Arch.MANDIBULAR


class CoordinateFrame(BaseModel):
    """Explicit millimetre frame. Geometry is never treated as frame-free."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    unit: Literal["mm"] = "mm"
    scale_verified: bool = False
    trusted: bool = False


class BoundsMm(BaseModel):
    """Optional axis-aligned bounds used only for deterministic proximity warnings."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    min_xyz: tuple[float, float, float]
    max_xyz: tuple[float, float, float]

    @model_validator(mode="after")
    def _ordered(self) -> BoundsMm:
        if any(lo > hi for lo, hi in zip(self.min_xyz, self.max_xyz, strict=True)):
            raise ValueError("bounds minimum must not exceed maximum")
        return self


class ToothGeometryRef(BaseModel):
    """Immutable reference to reviewed patient-derived per-tooth geometry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tooth: FdiToothId
    document_id: str = Field(min_length=1, max_length=128)
    source_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    frame: CoordinateFrame
    reviewed: bool = False
    per_tooth: bool = False
    trusted_tooth_local_frame: bool = False
    bounds_mm: BoundsMm | None = None

    @property
    def translation_renderable(self) -> bool:
        return self.reviewed and self.per_tooth and self.frame.scale_verified and self.frame.trusted

    @property
    def rotation_renderable(self) -> bool:
        return self.translation_renderable and self.trusted_tooth_local_frame


class ToothDelta(BaseModel):
    """Authored movement in explicit units; never a biological prediction."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    tooth: FdiToothId
    translate_x_mm: float = Field(default=0.0, ge=-20.0, le=20.0)
    translate_y_mm: float = Field(default=0.0, ge=-20.0, le=20.0)
    translate_z_mm: float = Field(default=0.0, ge=-20.0, le=20.0)
    rotate_tip_deg: float = Field(default=0.0, ge=-90.0, le=90.0)
    rotate_torque_deg: float = Field(default=0.0, ge=-90.0, le=90.0)
    rotate_rotation_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    coordinate_frame: str = Field(min_length=1, max_length=255)
    source: Literal["manual", "imported"] = "manual"

    @property
    def has_rotation(self) -> bool:
        return any((self.rotate_tip_deg, self.rotate_torque_deg, self.rotate_rotation_deg))


class Stage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0)
    deltas: tuple[ToothDelta, ...] = ()

    @field_validator("deltas")
    @classmethod
    def _unique_teeth(cls, value: tuple[ToothDelta, ...]) -> tuple[ToothDelta, ...]:
        ids = [delta.tooth.value for delta in value]
        if len(ids) != len(set(ids)):
            raise ValueError("a stage cannot contain duplicate tooth deltas")
        return value


class MovementCaps(BaseModel):
    """User-configurable engineering staging heuristics, not clinical clearance."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    linear_mm: float = Field(default=0.25, gt=0, le=5)
    vertical_mm: float = Field(default=0.10, gt=0, le=5)
    angular_deg: float = Field(default=1.0, gt=0, le=45)
    rotation_deg: float = Field(default=2.0, gt=0, le=90)


class MovementFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Literal[
        "movement-cap-exceeded",
        "scale-unverified",
        "frame-untrusted",
        "rotation-frame-untrusted",
        "geometry-unmapped",
        "proximity-warning",
    ]
    tooth: str | None = None
    stage_index: int | None = None
    message: str
    severity: Literal["notice", "warning"] = "warning"


class ToothPose(BaseModel):
    """Cumulative authored pose plus explicit rendering permissions."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    tooth: FdiToothId
    coordinate_frame: str
    translate_x_mm: float = 0.0
    translate_y_mm: float = 0.0
    translate_z_mm: float = 0.0
    rotate_tip_deg: float = 0.0
    rotate_torque_deg: float = 0.0
    rotate_rotation_deg: float = 0.0
    translation_renderable: bool = False
    rotation_renderable: bool = False

    def apply(self, delta: ToothDelta) -> ToothPose:
        if delta.tooth != self.tooth:
            raise ValueError("cannot apply movement for a different tooth")
        if delta.coordinate_frame != self.coordinate_frame:
            raise ValueError("cannot combine movements from different coordinate frames")
        return self.model_copy(
            update={
                "translate_x_mm": self.translate_x_mm + delta.translate_x_mm,
                "translate_y_mm": self.translate_y_mm + delta.translate_y_mm,
                "translate_z_mm": self.translate_z_mm + delta.translate_z_mm,
                "rotate_tip_deg": self.rotate_tip_deg + delta.rotate_tip_deg,
                "rotate_torque_deg": self.rotate_torque_deg + delta.rotate_torque_deg,
                "rotate_rotation_deg": self.rotate_rotation_deg + delta.rotate_rotation_deg,
            }
        )


class SimulationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    geometry: tuple[ToothGeometryRef, ...]
    stages: tuple[Stage, ...]
    caps: MovementCaps = Field(default_factory=MovementCaps)
    source: Literal["manual"] = "manual"

    @model_validator(mode="after")
    def _coherent(self) -> SimulationPlan:
        indexes = [stage.index for stage in self.stages]
        if indexes != list(range(len(self.stages))):
            raise ValueError("stage indexes must be contiguous and start at zero")
        geometry_by_tooth = {item.tooth.value: item for item in self.geometry}
        if len(geometry_by_tooth) != len(self.geometry):
            raise ValueError("duplicate per-tooth geometry mapping")
        for stage in self.stages:
            for delta in stage.deltas:
                geometry = geometry_by_tooth.get(delta.tooth.value)
                if geometry is None:
                    raise ValueError(f"movement references unmapped tooth {delta.tooth.value}")
                if delta.coordinate_frame != geometry.frame.id:
                    raise ValueError("movement coordinate frame does not match tooth geometry")
        return self


class SimulationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stages: tuple[Stage, ...]
    poses_by_stage: tuple[dict[str, ToothPose], ...]
    findings: tuple[MovementFinding, ...]
    reproducibility_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    synthetic_geometry: Literal[False] = False
    mutates_source_geometry: Literal[False] = False
    clinical_prediction: Literal[False] = False
    treatment_approval: Literal[False] = False


def evaluate_geometry(geometry: ToothGeometryRef) -> tuple[MovementFinding, ...]:
    findings: list[MovementFinding] = []
    if not geometry.per_tooth or not geometry.reviewed:
        findings.append(
            MovementFinding(
                code="geometry-unmapped",
                tooth=geometry.tooth.value,
                message="Reviewed per-tooth patient geometry is required before movement can be rendered.",
            )
        )
    if not geometry.frame.scale_verified:
        findings.append(
            MovementFinding(
                code="scale-unverified",
                tooth=geometry.tooth.value,
                message="Geometry scale is unverified; millimetre movement is disabled.",
            )
        )
    if not geometry.frame.trusted:
        findings.append(
            MovementFinding(
                code="frame-untrusted",
                tooth=geometry.tooth.value,
                message="Coordinate frame is not trusted; translation is disabled.",
            )
        )
    if not geometry.trusted_tooth_local_frame:
        findings.append(
            MovementFinding(
                code="rotation-frame-untrusted",
                tooth=geometry.tooth.value,
                message="Trusted tooth-local frame is unavailable; tip, torque and rotation are not rendered.",
                severity="notice",
            )
        )
    return tuple(findings)


def _steps_for_delta(delta: ToothDelta, caps: MovementCaps) -> int:
    ratios = (
        hypot(delta.translate_x_mm, delta.translate_y_mm) / caps.linear_mm,
        abs(delta.translate_z_mm) / caps.vertical_mm,
        abs(delta.rotate_tip_deg) / caps.angular_deg,
        abs(delta.rotate_torque_deg) / caps.angular_deg,
        abs(delta.rotate_rotation_deg) / caps.rotation_deg,
    )
    return max(1, ceil(max(ratios)))


def stage_movements(authored: tuple[ToothDelta, ...], caps: MovementCaps) -> tuple[Stage, ...]:
    """Split authored totals into deterministic cap-sized stages."""
    if not authored:
        return ()
    ids = [delta.tooth.value for delta in authored]
    if len(ids) != len(set(ids)):
        raise ValueError("authored movement must contain each tooth at most once")
    step_counts = {delta.tooth.value: _steps_for_delta(delta, caps) for delta in authored}
    count = max(step_counts.values())
    ordered = sorted(authored, key=lambda item: item.tooth.value)
    stages: list[Stage] = []
    for index in range(count):
        deltas: list[ToothDelta] = []
        for total in ordered:
            steps = step_counts[total.tooth.value]
            if index >= steps:
                continue
            deltas.append(
                total.model_copy(
                    update={
                        "translate_x_mm": total.translate_x_mm / steps,
                        "translate_y_mm": total.translate_y_mm / steps,
                        "translate_z_mm": total.translate_z_mm / steps,
                        "rotate_tip_deg": total.rotate_tip_deg / steps,
                        "rotate_torque_deg": total.rotate_torque_deg / steps,
                        "rotate_rotation_deg": total.rotate_rotation_deg / steps,
                    }
                )
            )
        stages.append(Stage(index=index, deltas=tuple(deltas)))
    return tuple(stages)


def evaluate_movement_caps(plan: SimulationPlan) -> tuple[MovementFinding, ...]:
    findings: list[MovementFinding] = []
    for geometry in plan.geometry:
        findings.extend(evaluate_geometry(geometry))
    for stage in plan.stages:
        for delta in stage.deltas:
            horizontal = hypot(delta.translate_x_mm, delta.translate_y_mm)
            exceeded = (
                horizontal > plan.caps.linear_mm
                or abs(delta.translate_z_mm) > plan.caps.vertical_mm
                or abs(delta.rotate_tip_deg) > plan.caps.angular_deg
                or abs(delta.rotate_torque_deg) > plan.caps.angular_deg
                or abs(delta.rotate_rotation_deg) > plan.caps.rotation_deg
            )
            if exceeded:
                findings.append(
                    MovementFinding(
                        code="movement-cap-exceeded",
                        tooth=delta.tooth.value,
                        stage_index=stage.index,
                        message="Authored stage exceeds the configured deterministic movement heuristic.",
                    )
                )
    return tuple(findings)


def cumulative_poses(plan: SimulationPlan) -> tuple[dict[str, ToothPose], ...]:
    geometry_by_tooth = {item.tooth.value: item for item in plan.geometry}
    current: dict[str, ToothPose] = {}
    output: list[dict[str, ToothPose]] = []
    for stage in plan.stages:
        for delta in stage.deltas:
            geometry = geometry_by_tooth[delta.tooth.value]
            pose = current.get(delta.tooth.value) or ToothPose(
                tooth=delta.tooth,
                coordinate_frame=geometry.frame.id,
                translation_renderable=geometry.translation_renderable,
                rotation_renderable=geometry.rotation_renderable,
            )
            current[delta.tooth.value] = pose.apply(delta)
        output.append(dict(current))
    return tuple(output)


def proximity_findings(
    geometry: tuple[ToothGeometryRef, ...], minimum_gap_mm: float = 0.05
) -> tuple[MovementFinding, ...]:
    """Static AABB proximity only; not collision physics or biological modelling."""
    if minimum_gap_mm < 0 or not math.isfinite(minimum_gap_mm):
        raise ValueError("minimum gap must be a finite non-negative value")
    findings: list[MovementFinding] = []
    bounded = [item for item in geometry if item.bounds_mm is not None]
    for left_index, left in enumerate(bounded):
        assert left.bounds_mm is not None
        for right in bounded[left_index + 1 :]:
            assert right.bounds_mm is not None
            gaps = []
            for axis in range(3):
                a0, a1 = left.bounds_mm.min_xyz[axis], left.bounds_mm.max_xyz[axis]
                b0, b1 = right.bounds_mm.min_xyz[axis], right.bounds_mm.max_xyz[axis]
                gaps.append(max(b0 - a1, a0 - b1, 0.0))
            distance = math.sqrt(sum(gap * gap for gap in gaps))
            if distance <= minimum_gap_mm:
                findings.append(
                    MovementFinding(
                        code="proximity-warning",
                        tooth=left.tooth.value,
                        message=(
                            f"Static bounds for FDI {left.tooth.value} and {right.tooth.value} "
                            f"are within {minimum_gap_mm:.3f} mm; engineering review only."
                        ),
                        severity="notice",
                    )
                )
    return tuple(findings)


def reproducibility_digest(plan: SimulationPlan) -> str:
    canonical = json.dumps(
        plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def simulate(plan: SimulationPlan) -> SimulationResult:
    findings = evaluate_movement_caps(plan) + proximity_findings(plan.geometry)
    return SimulationResult(
        stages=plan.stages,
        poses_by_stage=cumulative_poses(plan),
        findings=findings,
        reproducibility_digest=reproducibility_digest(plan),
    )
