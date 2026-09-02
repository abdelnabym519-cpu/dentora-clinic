"""Pure domain layer for orthodontic planning.

No FastAPI, no SQLAlchemy, no I/O — everything here is deterministic
and unit-testable in isolation. The service layer converts ORM rows and
provider output into these structures; the constraint layer
(:mod:`app.modules.orthodontic_planning.constraints`) validates any
plan — regardless of which provider produced it — against the same
structures.

Clinical safety posture: this module is **decision support only**. It
produces *proposals* that a clinician must review; nothing here writes
to other modules (odontogram / treatment_plan are read-only or
untouched), and nothing here can execute autonomously.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from .constants import (
    MIN_CHARTED_PERMANENT_TEETH,
    MOVEMENT_LIMITS,
    REQUIRED_MEASUREMENTS,
)

__all__ = [
    "DentitionSnapshot",
    "InsufficientDataError",
    "Movement",
    "PlannerCase",
    "Stage",
    "ToothSnapshot",
    "arch_of",
    "build_sufficiency",
    "is_valid_permanent_fdi",
    "permanent_incisors",
    "first_molars",
]


class InsufficientDataError(RuntimeError):
    """Raised when a case cannot be planned (fail-closed).

    Carries the list of missing/insufficient inputs so the API can tell
    the clinician exactly what to chart before asking for a plan again.
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        super().__init__(f"Insufficient data for orthodontic planning: {self.missing}")


# --- FDI helpers (permanent dentition) ---------------------------------------


def is_valid_permanent_fdi(tooth_number: int) -> bool:
    """FDI permanent notation: quadrant 1-4, position 1-8 (11..48)."""
    quadrant, position = divmod(tooth_number, 10)
    return 1 <= quadrant <= 4 and 1 <= position <= 8


def arch_of(tooth_number: int) -> str:
    """``upper`` for quadrants 1-2, ``lower`` for quadrants 3-4."""
    quadrant = tooth_number // 10
    if quadrant in (1, 2):
        return "upper"
    if quadrant in (3, 4):
        return "lower"
    raise ValueError(f"Tooth {tooth_number} is not a valid permanent FDI number")


def permanent_incisors(arch: str) -> tuple[int, ...]:
    """Central + lateral incisors of one arch, sorted by FDI."""
    quadrants = (1, 2) if arch == "upper" else (3, 4)
    teeth: list[int] = []
    for q in quadrants:
        teeth.extend(q * 10 + p for p in (1, 2))
    return tuple(sorted(teeth))


def first_molars(arch: str) -> tuple[int, ...]:
    """Permanent first molars of one arch (16/26 or 36/46)."""
    quadrants = (1, 2) if arch == "upper" else (3, 4)
    return tuple(sorted(q * 10 + 6 for q in quadrants))


# --- Snapshot structures ------------------------------------------------------


@dataclass(frozen=True)
class ToothSnapshot:
    """Immutable per-tooth state copied from the odontogram at
    assessment time (loose coupling: plain values, no FK/ORM import)."""

    tooth_number: int
    dentition: str  # "permanent" | "deciduous"
    present: bool
    is_displaced: bool = False
    is_rotated: bool = False


@dataclass(frozen=True)
class DentitionSnapshot:
    """Immutable dentition state used by planning + validation."""

    teeth: tuple[ToothSnapshot, ...] = field(default_factory=tuple)

    def get(self, tooth_number: int) -> ToothSnapshot | None:
        for tooth in self.teeth:
            if tooth.tooth_number == tooth_number:
                return tooth
        return None

    def permanent_present(self) -> tuple[int, ...]:
        return tuple(
            sorted(t.tooth_number for t in self.teeth if t.dentition == "permanent" and t.present)
        )

    def deciduous_present(self) -> tuple[int, ...]:
        return tuple(
            sorted(t.tooth_number for t in self.teeth if t.dentition == "deciduous" and t.present)
        )

    def is_plannable_tooth(self, tooth_number: int) -> bool:
        tooth = self.get(tooth_number)
        return tooth is not None and tooth.dentition == "permanent" and tooth.present

    def charted_permanent_count(self) -> int:
        return len(self.permanent_present())


def build_sufficiency(
    *,
    measurements: dict[str, object],
    dentition: DentitionSnapshot,
) -> dict[str, object]:
    """Deterministic data-sufficiency report for a case.

    Returns ``{"is_plannable", "missing", "score", "charted_permanent"}``.
    ``score`` is the fraction of required measurements present (0..1);
    plannability additionally requires odontogram coverage.
    """
    missing = [name for name in REQUIRED_MEASUREMENTS if measurements.get(name) is None]
    charted = dentition.charted_permanent_count()
    if charted < MIN_CHARTED_PERMANENT_TEETH:
        missing.append(f"odontogram_charted_permanent_teeth(<{MIN_CHARTED_PERMANENT_TEETH})")
    score = round(
        (len(REQUIRED_MEASUREMENTS) - len([m for m in missing if m in REQUIRED_MEASUREMENTS]))
        / len(REQUIRED_MEASUREMENTS),
        4,
    )
    return {
        "is_plannable": len(missing) == 0,
        "missing": missing,
        "score": score,
        "charted_permanent": charted,
    }


# --- Plan structures -----------------------------------------------------------


@dataclass(frozen=True)
class Movement:
    """One tooth movement proposal. ``magnitude`` is positive; direction
    is encoded by ``movement_type`` (e.g. proclination vs retroclination)."""

    tooth: int
    movement_type: str
    magnitude: float

    def __post_init__(self) -> None:
        if not is_valid_permanent_fdi(self.tooth):
            raise ValueError(f"Invalid permanent FDI tooth number: {self.tooth}")
        if self.movement_type not in MOVEMENT_LIMITS:
            raise ValueError(f"Unknown movement type: {self.movement_type}")
        if self.magnitude <= 0:
            raise ValueError(f"Magnitude must be positive, got {self.magnitude}")

    def as_dict(self) -> dict[str, object]:
        return {
            "tooth": self.tooth,
            "movement_type": self.movement_type,
            "magnitude": round(self.magnitude, 2),
        }


@dataclass(frozen=True)
class Stage:
    """One aligner/wire stage: at most one movement per tooth."""

    label: str
    movements: tuple[Movement, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        teeth = [m.tooth for m in self.movements]
        if len(teeth) != len(set(teeth)):
            raise ValueError("A stage may contain at most one movement per tooth")

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "movements": [m.as_dict() for m in self.movements],
        }


@dataclass(frozen=True)
class PlannerCase:
    """Everything a provider may see for one case (ids + measurements +
    immutable dentition snapshot). Providers receive no ORM objects."""

    patient_id: UUID
    skeletal_pattern: str | None
    growth_stage: str | None
    overjet_mm: float | None
    overbite_mm: float | None
    crowding_upper_mm: float | None
    crowding_lower_mm: float | None
    molar_relation_left: str | None
    molar_relation_right: str | None
    canine_relation_left: str | None
    canine_relation_right: str | None
    posterior_crossbite: bool
    objectives: tuple[str, ...]
    dentition: DentitionSnapshot
    sufficiency: dict[str, object]

    def require_plannable(self) -> None:
        """Fail closed unless the case is complete."""
        missing = list(self.sufficiency.get("missing", []))
        if not self.objectives:
            missing.append("objectives(non_empty)")
        if missing:
            raise InsufficientDataError(missing)

    def measurements(self) -> dict[str, object]:
        return {
            "skeletal_pattern": self.skeletal_pattern,
            "growth_stage": self.growth_stage,
            "overjet_mm": self.overjet_mm,
            "overbite_mm": self.overbite_mm,
            "crowding_upper_mm": self.crowding_upper_mm,
            "crowding_lower_mm": self.crowding_lower_mm,
            "molar_relation_left": self.molar_relation_left,
            "molar_relation_right": self.molar_relation_right,
            "canine_relation_left": self.canine_relation_left,
            "canine_relation_right": self.canine_relation_right,
        }
