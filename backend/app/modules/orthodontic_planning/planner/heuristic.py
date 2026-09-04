"""Deterministic reference planner (``heuristic_v1``).

A transparent, rule-based staged planner used as (a) the shipped
decision-support policy and (b) the executable specification of the
reward/transition semantics a future learned ML/RL policy must respect.

Design (all steps deterministic, no randomness, no external model):

1. Fail closed unless the case is complete (``PlannerCase.require_
   plannable``) — missing measurements or under-charted odontogram
   raise :class:`InsufficientDataError`.
2. Build per-tooth movement *streams* with fixed totals:
   - rotation correction for charted ``is_rotated`` teeth,
   - uprighting for charted ``is_displaced`` teeth,
   - incisor proclination + first-molar distalization to relieve
     crowding within the non-extraction envelope,
   - upper-incisor retroclination to reduce overjet within the
     non-surgical envelope.
3. Slice streams into stages at the per-stage caps (one movement per
   tooth per stage), FDI-sorted for deterministic output.
4. Score the plan with the fixed reward weighting
   (:func:`score_proposal`) and report confidence as
   ``data-sufficiency × HEURISTIC_MAX_CONFIDENCE``.

The planner never persists anything and never mutates other modules;
its output is re-validated by ``constraints.evaluate_stages`` before
storage. Full-correction targets for coarse odontogram flags (rotated/
displaced) are documented defaults — this granularity limit is always
surfaced in ``uncertainty``.
"""

from __future__ import annotations

import math

from ..constants import (
    EPSILON_MM,
    HEURISTIC_MAX_CONFIDENCE,
    MAX_LOWER_PROCLINATION_MM,
    MAX_OVERJET_REDUCTION_MM,
    MAX_STAGES,
    MAX_UPPER_PROCLINATION_MM,
    MOLAR_DISTALIZATION_MAX_PER_SIDE_MM,
    MOVEMENT_LIMITS,
    PROVIDER_HEURISTIC,
    SCORE_WEIGHT_ALIGNMENT,
    SCORE_WEIGHT_ENVELOPE,
    SCORE_WEIGHT_STAGE_EFFICIENCY,
    TARGET_OVERJET_MM,
)
from ..constraints import space_relief_by_arch
from ..domain import (
    Movement,
    PlannerCase,
    Stage,
    first_molars,
    permanent_incisors,
)
from .base import InsufficientDataError, PlanSuggestion

PROVIDER_NAME = PROVIDER_HEURISTIC
PROVIDER_VERSION = "heuristic_v1.0"

# Documented full-correction targets for coarse odontogram flags.
ROTATED_TOTAL_DEG = 30.0
DISPLACED_TOTAL_DEG = 20.0

UPPER_INCISORS = permanent_incisors("upper")
LOWER_INCISORS = permanent_incisors("lower")
UPPER_FIRST_MOLARS = first_molars("upper")
LOWER_FIRST_MOLARS = first_molars("lower")


class HeuristicPlanner:
    """The shipped deterministic planner (protocol: PlanningProvider)."""

    name = PROVIDER_NAME
    version = PROVIDER_VERSION

    def propose_plan(self, case: PlannerCase) -> PlanSuggestion:
        case.require_plannable()  # fail closed

        streams = self._movement_streams(case)
        stages = self._slice_into_stages(streams)
        score, alignment_ratio, envelope_ok = score_proposal(case, stages)

        uncertainty = self._uncertainty_notes(case, envelope_ok)
        confidence = round(float(case.sufficiency.get("score", 0.0)) * HEURISTIC_MAX_CONFIDENCE, 4)

        return PlanSuggestion(
            stages=tuple(stages),
            provider=self.name,
            provider_version=self.version,
            score=score,
            confidence=confidence,
            uncertainty=tuple(uncertainty),
            rationale=self._rationale(case, stages, alignment_ratio, envelope_ok),
        )

    # --- streams ---------------------------------------------------------------

    def _movement_streams(self, case: PlannerCase) -> list[dict[str, object]]:
        """Ordered movement streams: (tooth, type, total). FDI/type sorted."""
        dentition = case.dentition
        streams: list[dict[str, object]] = []

        # 1) Alignment of flagged teeth.
        for tooth in dentition.permanent_present():
            snapshot = dentition.get(tooth)
            assert snapshot is not None  # noqa: S101 — invariant of the snapshot
            if snapshot.is_rotated:
                streams.append(
                    {
                        "tooth": tooth,
                        "movement_type": "rotation_correction",
                        "total": ROTATED_TOTAL_DEG,
                    }
                )
            if snapshot.is_displaced:
                streams.append(
                    {"tooth": tooth, "movement_type": "uprighting", "total": DISPLACED_TOTAL_DEG}
                )

        # 2) Crowding relief per arch (proclination → distalization).
        for arch, crowding, proclination_cap, incisors, molars in (
            (
                "upper",
                case.crowding_upper_mm,
                MAX_UPPER_PROCLINATION_MM,
                UPPER_INCISORS,
                UPPER_FIRST_MOLARS,
            ),
            (
                "lower",
                case.crowding_lower_mm,
                MAX_LOWER_PROCLINATION_MM,
                LOWER_INCISORS,
                LOWER_FIRST_MOLARS,
            ),
        ):
            demand = float(crowding or 0.0)
            if demand <= EPSILON_MM:
                continue
            present_incisors = [t for t in incisors if dentition.is_plannable_tooth(t)]
            if not present_incisors:
                raise InsufficientDataError([f"odontogram_{arch}_incisors(none charted)"])
            proclination_total = min(demand, proclination_cap)
            per_tooth = round(proclination_total / len(present_incisors), 2)
            for tooth in present_incisors:
                if per_tooth >= EPSILON_MM:
                    streams.append(
                        {"tooth": tooth, "movement_type": "proclination", "total": per_tooth}
                    )
            remaining = demand - proclination_total
            if remaining > EPSILON_MM:
                present_molars = [t for t in molars if dentition.is_plannable_tooth(t)]
                if present_molars:
                    per_side = min(
                        round(remaining / len(present_molars), 2),
                        MOLAR_DISTALIZATION_MAX_PER_SIDE_MM,
                    )
                    for tooth in present_molars:
                        if per_side >= EPSILON_MM:
                            streams.append(
                                {
                                    "tooth": tooth,
                                    "movement_type": "distalization",
                                    "total": per_side,
                                }
                            )

        # 3) Overjet reduction (upper incisor retroclination, envelope-capped).
        if (
            "correct_overjet" in case.objectives
            and case.overjet_mm is not None
            and case.overjet_mm > TARGET_OVERJET_MM
        ):
            reduction = min(case.overjet_mm - TARGET_OVERJET_MM, MAX_OVERJET_REDUCTION_MM)
            present_upper_incisors = [
                t for t in UPPER_INCISORS if case.dentition.is_plannable_tooth(t)
            ]
            if present_upper_incisors:
                per_tooth = round(reduction / len(present_upper_incisors), 2)
                for tooth in present_upper_incisors:
                    if per_tooth >= EPSILON_MM:
                        streams.append(
                            {
                                "tooth": tooth,
                                "movement_type": "retroclination",
                                "total": per_tooth,
                            }
                        )

        streams.sort(key=lambda s: (int(s["tooth"]), str(s["movement_type"])))
        return streams

    # --- staging -----------------------------------------------------------------

    def _slice_into_stages(self, streams: list[dict[str, object]]) -> list[Stage]:
        """Slice streams into stages at the per-stage caps.

        Raises InsufficientDataError if the required stage count exceeds
        MAX_STAGES (cannot happen with shipped bounds; guards future
        constant edits deterministically).
        """
        rounds: dict[int, list[Movement]] = {}
        max_round = 0
        for stream in streams:
            tooth = int(stream["tooth"])
            movement_type = str(stream["movement_type"])
            total = float(stream["total"])
            per_stage = MOVEMENT_LIMITS[movement_type]["per_stage"]
            remaining = total
            round_index = 0
            while remaining > EPSILON_MM and round_index < MAX_STAGES:
                magnitude = round(min(per_stage, remaining), 2)
                if magnitude >= EPSILON_MM:
                    rounds.setdefault(round_index, []).append(
                        Movement(tooth=tooth, movement_type=movement_type, magnitude=magnitude)
                    )
                remaining -= magnitude
                round_index += 1
                max_round = max(max_round, round_index)
        if remaining_error := [
            s for s in streams if float(s["total"]) - _delivered(rounds, s) > EPSILON_MM
        ]:
            raise InsufficientDataError(
                [f"plan_horizon({len(remaining_error)} streams exceed {MAX_STAGES} stages)"]
            )

        stages: list[Stage] = []
        for index in range(max_round):
            movements = _dedupe_per_tooth(rounds.get(index, []))
            if movements:
                stages.append(
                    Stage(
                        label=f"Stage {index + 1} — leveling, alignment & space management",
                        movements=tuple(sorted(movements, key=lambda m: m.tooth)),
                    )
                )
        return stages

    # --- reporting -----------------------------------------------------------------

    def _uncertainty_notes(self, case: PlannerCase, envelope_ok: bool) -> list[str]:
        notes: list[str] = []
        if case.dentition.deciduous_present():
            notes.append(
                "Mixed dentition: deciduous teeth "
                f"{list(case.dentition.deciduous_present())} present — v1 plans the "
                "permanent dentition only"
            )
        if case.growth_stage == "adult" and case.skeletal_pattern in ("class_ii", "class_iii"):
            notes.append(
                "Adult skeletal discrepancy: no growth modification is modeled — skeletal "
                "component requires specialist evaluation"
            )
        if case.posterior_crossbite or "correct_crossbite" in case.objectives:
            notes.append(
                "Transverse/crossbite correction is outside the v1 movement model — "
                "requires clinical evaluation (RME/quad-helix options)"
            )
        if "correct_overbite" in case.objectives:
            notes.append(
                "Overbite correction is not explicitly staged in v1; incisor movements may "
                "partially affect it"
            )
        if not envelope_ok:
            notes.append(
                "Crowding demand exceeds the planned non-extraction relief — see the "
                "space-deficit finding; specialist options (extraction/transverse) not modeled"
            )
        notes.append(
            "Deterministic reference policy (no biomechanical simulation): confirm all "
            "magnitudes clinically before approval"
        )
        return notes

    def _rationale(
        self,
        case: PlannerCase,
        stages: list[Stage],
        alignment_ratio: float,
        envelope_ok: bool,
    ) -> str:
        relief = space_relief_by_arch(tuple(stages))
        rotated = sum(
            1
            for t in case.dentition.permanent_present()
            if case.dentition.get(t) and case.dentition.get(t).is_rotated  # type: ignore[union-attr]
        )
        displaced = sum(
            1
            for t in case.dentition.permanent_present()
            if case.dentition.get(t) and case.dentition.get(t).is_displaced  # type: ignore[union-attr]
        )
        parts = [
            f"{len(stages)} stages; align {rotated} rotated / {displaced} displaced teeth",
            f"space relief upper {round(relief['upper'], 2)} mm / lower {round(relief['lower'], 2)} mm",
            f"alignment resolution {round(alignment_ratio * 100, 1)}%",
        ]
        parts.append("within non-extraction envelope" if envelope_ok else "space deficit flagged")
        return "; ".join(parts)


def _delivered(rounds: dict[int, list[Movement]], stream: dict[str, object]) -> float:
    tooth = int(stream["tooth"])
    movement_type = str(stream["movement_type"])
    return sum(
        m.magnitude
        for movements in rounds.values()
        for m in movements
        if m.tooth == tooth and m.movement_type == movement_type
    )


def _dedupe_per_tooth(movements: list[Movement]) -> list[Movement]:
    """Keep the first movement per tooth (deterministic input order)."""
    seen: set[int] = set()
    kept: list[Movement] = []
    for movement in movements:
        if movement.tooth in seen:
            continue
        seen.add(movement.tooth)
        kept.append(movement)
    return kept


def score_proposal(
    case: PlannerCase,
    stages: list[Stage],
) -> tuple[float, float, bool]:
    """Deterministic reward for a plan (the score a future learned
    policy must also be evaluated against).

    Returns ``(score, alignment_ratio, envelope_ok)`` where score =
    0.6·alignment + 0.25·envelope + 0.15·stage_efficiency, rounded 4dp.
    """
    demand = {
        "upper": float(case.crowding_upper_mm or 0.0),
        "lower": float(case.crowding_lower_mm or 0.0),
    }
    relief = space_relief_by_arch(tuple(stages))
    resolved = sum(min(demand[arch], relief[arch]) for arch in ("upper", "lower"))
    total_demand = demand["upper"] + demand["lower"]
    alignment_ratio = 1.0 if total_demand <= EPSILON_MM else round(resolved / total_demand, 4)

    envelope_ok = all(demand[arch] - relief[arch] <= EPSILON_MM for arch in ("upper", "lower"))
    stage_efficiency = 1.0 if not stages else max(0.0, 1.0 - len(stages) / MAX_STAGES)

    score = round(
        SCORE_WEIGHT_ALIGNMENT * alignment_ratio
        + SCORE_WEIGHT_ENVELOPE * (1.0 if envelope_ok else 0.0)
        + SCORE_WEIGHT_STAGE_EFFICIENCY * stage_efficiency,
        4,
    )
    return score, alignment_ratio, envelope_ok


# Deterministic helper reused by tests.
def planned_months(stage_count: int, weeks_per_stage: int, weeks_per_month: float) -> int:
    return max(1, math.ceil(stage_count * weeks_per_stage / weeks_per_month))
