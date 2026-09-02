"""Deterministic constraint/safety layer for orthodontic plans.

This module is the **single gate** every plan must pass, regardless of
which provider (reference heuristic or a future learned policy)
produced it. It is pure, deterministic, model-free, and fail-closed:

* Hard violations ⇒ the plan is structurally unsafe and MUST NOT be
  persisted or shown as plannable. The service refuses and audits.
* Soft findings (e.g. crowding beyond the non-extraction envelope) do
  not invalidate the proposal but MUST be surfaced to the reviewing
  clinician.

No learned component ever bypasses this layer — it sits outside the
provider abstraction by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import (
    EPSILON_MM,
    MAX_OVERJET_REDUCTION_MM,
    MAX_STAGES,
    MOLAR_DISTALIZATION_MAX_PER_SIDE_MM,
    MOVEMENT_LIMITS,
    PROCLINATION_SPACE_GAIN_PER_MM,
    TARGET_OVERJET_MM,
)
from .domain import (
    DentitionSnapshot,
    PlannerCase,
    Stage,
    arch_of,
    first_molars,
    is_valid_permanent_fdi,
    permanent_incisors,
)

SEVERITY_HARD = "hard"
SEVERITY_SOFT = "soft"

UPPER_INCISORS = permanent_incisors("upper")
LOWER_INCISORS = permanent_incisors("lower")
UPPER_FIRST_MOLARS = first_molars("upper")
LOWER_FIRST_MOLARS = first_molars("lower")


@dataclass(frozen=True)
class ConstraintViolation:
    """One deterministic finding. ``code`` values are stable API surface
    (frontend + audit logs key off them)."""

    code: str
    severity: str  # "hard" | "soft"
    message: str
    tooth: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "tooth": self.tooth,
        }


@dataclass(frozen=True)
class ConstraintReport:
    """Result of validating one full plan against the case."""

    violations: tuple[ConstraintViolation, ...] = field(default_factory=tuple)

    @property
    def hard(self) -> tuple[ConstraintViolation, ...]:
        return tuple(v for v in self.violations if v.severity == SEVERITY_HARD)

    @property
    def soft(self) -> tuple[ConstraintViolation, ...]:
        return tuple(v for v in self.violations if v.severity == SEVERITY_SOFT)

    @property
    def is_valid(self) -> bool:
        return len(self.hard) == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "is_valid": self.is_valid,
            "hard_count": len(self.hard),
            "soft_count": len(self.soft),
            "violations": [v.as_dict() for v in self.violations],
        }


def _totals(stages: tuple[Stage, ...]) -> dict[tuple[int, str], float]:
    """Cumulative magnitude per (tooth, movement_type) across stages."""
    totals: dict[tuple[int, str], float] = {}
    for stage in stages:
        for movement in stage.movements:
            key = (movement.tooth, movement.movement_type)
            totals[key] = totals.get(key, 0.0) + movement.magnitude
    return totals


def space_relief_by_arch(stages: tuple[Stage, ...]) -> dict[str, float]:
    """Arch-length relief credited by the v1 model (mm, per arch).

    Transparent accounting: incisor proclination × gain factor + first
    molar distalization (capped per side). IPR / extraction / transverse
    channels are intentionally NOT modeled in v1. Movements on unknown
    or non-permanent teeth contribute nothing here (the hard-violation
    checks report them separately).
    """
    totals = _totals(stages)
    relief = {"upper": 0.0, "lower": 0.0}
    for (tooth, movement_type), magnitude in totals.items():
        if not is_valid_permanent_fdi(tooth):
            continue
        arch = arch_of(tooth)
        if movement_type == "proclination" and tooth in (UPPER_INCISORS + LOWER_INCISORS):
            relief[arch] += magnitude * PROCLINATION_SPACE_GAIN_PER_MM
        elif movement_type == "distalization" and tooth in (
            UPPER_FIRST_MOLARS + LOWER_FIRST_MOLARS
        ):
            relief[arch] += min(magnitude, MOLAR_DISTALIZATION_MAX_PER_SIDE_MM)
    return relief


def evaluate_stages(
    case: PlannerCase,
    stages: tuple[Stage, ...],
) -> ConstraintReport:
    """Validate a full staged plan against a case. Deterministic."""
    violations: list[ConstraintViolation] = []
    dentition: DentitionSnapshot = case.dentition

    # --- plan shape ---------------------------------------------------------
    if len(stages) < 1:
        violations.append(
            ConstraintViolation("H_EMPTY_PLAN", SEVERITY_HARD, "Plan contains no stages")
        )
    if len(stages) > MAX_STAGES:
        violations.append(
            ConstraintViolation(
                "H_TOO_MANY_STAGES",
                SEVERITY_HARD,
                f"Plan has {len(stages)} stages (max {MAX_STAGES})",
            )
        )

    seen_in_stage: set[int] = set()
    for index, stage in enumerate(stages):
        seen_in_stage.clear()
        for movement in stage.movements:
            tooth = movement.tooth
            # Presence + dentition (fail-closed on missing/unknown teeth).
            snapshot = dentition.get(tooth)
            if snapshot is None:
                violations.append(
                    ConstraintViolation(
                        "H_UNKNOWN_TOOTH",
                        SEVERITY_HARD,
                        f"Stage {index + 1}: tooth {tooth} is not in the dentition snapshot",
                        tooth,
                    )
                )
            elif not snapshot.present:
                violations.append(
                    ConstraintViolation(
                        "H_MISSING_TOOTH",
                        SEVERITY_HARD,
                        f"Stage {index + 1}: tooth {tooth} is charted missing",
                        tooth,
                    )
                )
            elif snapshot.dentition != "permanent":
                violations.append(
                    ConstraintViolation(
                        "H_DECIDUOUS_TOOTH",
                        SEVERITY_HARD,
                        f"Stage {index + 1}: tooth {tooth} is deciduous; "
                        "v1 plans permanent dentition only",
                        tooth,
                    )
                )
            # Per-stage bound.
            limits = MOVEMENT_LIMITS.get(movement.movement_type)
            if limits is None:
                violations.append(
                    ConstraintViolation(
                        "H_MOVEMENT_TYPE",
                        SEVERITY_HARD,
                        f"Stage {index + 1}: unknown movement type '{movement.movement_type}'",
                        tooth,
                    )
                )
            elif movement.magnitude > limits["per_stage"] + 1e-9:
                violations.append(
                    ConstraintViolation(
                        "H_STAGE_BOUND",
                        SEVERITY_HARD,
                        f"Stage {index + 1}: tooth {tooth} {movement.movement_type} "
                        f"{movement.magnitude} exceeds per-stage cap {limits['per_stage']}",
                        tooth,
                    )
                )
            if tooth in seen_in_stage:
                violations.append(
                    ConstraintViolation(
                        "H_ONE_MOVEMENT_PER_TOOTH",
                        SEVERITY_HARD,
                        f"Stage {index + 1}: tooth {tooth} moved more than once",
                        tooth,
                    )
                )
            seen_in_stage.add(tooth)

    # Per-tooth totals.
    totals = _totals(stages)
    for (tooth, movement_type), total in sorted(totals.items()):
        limits = MOVEMENT_LIMITS.get(movement_type)
        if limits is not None and total > limits["per_tooth_total"] + 1e-9:
            violations.append(
                ConstraintViolation(
                    "H_TOTAL_BOUND",
                    SEVERITY_HARD,
                    f"Tooth {tooth} cumulative {movement_type} {round(total, 2)} exceeds "
                    f"per-tooth cap {limits['per_tooth_total']}",
                    tooth,
                )
            )

    # --- overjet envelope (hard) ---------------------------------------------
    overjet = case.overjet_mm
    upper_retro_total = sum(
        total
        for (tooth, movement_type), total in totals.items()
        if movement_type == "retroclination" and tooth in UPPER_INCISORS
    )
    if overjet is not None:
        # How much upper-incisor retroclination the overjet can absorb.
        absorbable = overjet - TARGET_OVERJET_MM
        allowed = min(max(absorbable, 0.0), MAX_OVERJET_REDUCTION_MM)
        if upper_retro_total > allowed + EPSILON_MM:
            violations.append(
                ConstraintViolation(
                    "H_OVERJET_ENVELOPE",
                    SEVERITY_HARD,
                    f"Planned upper retroclination {round(upper_retro_total, 2)} mm exceeds "
                    f"the overjet envelope ({round(allowed, 2)} mm for overjet {overjet} mm; "
                    f"target {TARGET_OVERJET_MM} mm, non-surgical cap "
                    f"{MAX_OVERJET_REDUCTION_MM} mm)",
                )
            )

    # --- space envelope (soft, prominently surfaced) --------------------------
    if case.crowding_upper_mm is not None:
        _check_space_deficit(
            violations, "upper", case.crowding_upper_mm, space_relief_by_arch(stages)["upper"]
        )
    if case.crowding_lower_mm is not None:
        _check_space_deficit(
            violations, "lower", case.crowding_lower_mm, space_relief_by_arch(stages)["lower"]
        )

    return ConstraintReport(violations=tuple(violations))


def _check_space_deficit(
    violations: list[ConstraintViolation],
    arch: str,
    demand: float,
    relief: float,
) -> None:
    if demand - relief > EPSILON_MM:
        violations.append(
            ConstraintViolation(
                "S_SPACE_DEFICIT",
                SEVERITY_SOFT,
                f"{arch.capitalize()} crowding {round(demand, 2)} mm exceeds the planned "
                f"non-extraction relief ({round(relief, 2)} mm) by {round(demand - relief, 2)} mm "
                "— outside the v1 envelope; extraction/transverse options require a "
                "specialist decision",
            )
        )
