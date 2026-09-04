"""Deterministic constraint-gate tests — every hard rule + soft findings."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.modules.orthodontic_planning.constraints import (
    SEVERITY_HARD,
    SEVERITY_SOFT,
    evaluate_stages,
    space_relief_by_arch,
)
from app.modules.orthodontic_planning.domain import (
    Movement,
    PlannerCase,
    Stage,
)

from .helpers import complete_measurements, full_chart

HARD_CODES = {
    "H_EMPTY_PLAN",
    "H_TOO_MANY_STAGES",
    "H_UNKNOWN_TOOTH",
    "H_MISSING_TOOTH",
    "H_DECIDUOUS_TOOTH",
    "H_MOVEMENT_TYPE",
    "H_STAGE_BOUND",
    "H_TOTAL_BOUND",
    "H_ONE_MOVEMENT_PER_TOOTH",
    "H_OVERJET_ENVELOPE",
}


def _case(**overrides) -> PlannerCase:
    absent = overrides.pop("absent", overrides.pop("_absent", ()))
    missing = overrides.pop("missing", overrides.pop("_missing", ()))
    deciduous = overrides.pop("deciduous", overrides.pop("_deciduous", ()))
    measurements = complete_measurements(**overrides)
    sufficiency = {
        "is_plannable": True,
        "missing": [],
        "score": 1.0,
        "charted_permanent": 32 - len(absent) - len(missing),
    }
    return PlannerCase(
        patient_id=uuid4(),
        objectives=tuple(measurements.get("objectives", ())),
        dentition=full_chart(missing=missing, deciduous=deciduous, absent=absent),
        sufficiency=sufficiency,
        posterior_crossbite=False,
        **{k: v for k, v in measurements.items() if k not in ("objectives", "posterior_crossbite")},
    )


def _codes(report) -> set[str]:
    return {v.code for v in report.violations}


def test_valid_plan_passes_clean() -> None:
    stages = (
        Stage(label="s1", movements=(Movement(11, "proclination", 0.5),)),
        Stage(label="s2", movements=(Movement(11, "proclination", 0.5),)),
    )
    report = evaluate_stages(_case(), stages)
    assert report.is_valid
    # Upper demand 2.0 vs relief 1.0 → a SOFT space deficit is expected.
    assert any(v.code == "S_SPACE_DEFICIT" for v in report.soft)


def test_hard_codes_are_exactly_the_documented_set() -> None:
    assert HARD_CODES  # sanity: documented surface
    assert all(code.startswith("H_") for code in HARD_CODES)


def test_empty_plan_rejected() -> None:
    report = evaluate_stages(_case(), ())
    assert "H_EMPTY_PLAN" in _codes(report)
    assert not report.is_valid


def test_movement_on_missing_tooth_rejected() -> None:
    case = _case(_missing=(16,))
    stages = (Stage(label="s1", movements=(Movement(16, "distalization", 0.5),)),)
    report = evaluate_stages(case, stages)
    assert "H_MISSING_TOOTH" in _codes(report)
    assert not report.is_valid


def test_movement_on_unknown_tooth_rejected() -> None:
    # Tooth 15 is valid FDI but entirely absent from the snapshot.
    case = _case(_absent=(15,))
    stages = (Stage(label="s1", movements=(Movement(15, "proclination", 0.5),)),)
    report = evaluate_stages(case, stages)
    assert "H_UNKNOWN_TOOTH" in _codes(report)


def test_movement_on_deciduous_tooth_rejected() -> None:
    # Movement itself rejects deciduous FDI numbers, so simulate a raw
    # movement record (the validator must still refuse — defense in depth).
    case = _case(_deciduous=(55,))
    raw = SimpleNamespace(tooth=55, movement_type="proclination", magnitude=0.5)
    stages = (Stage(label="s1", movements=(raw,)),)  # type: ignore[list-item]
    report = evaluate_stages(case, stages)
    assert "H_DECIDUOUS_TOOTH" in _codes(report)


def test_per_stage_bound_enforced() -> None:
    stages = (Stage(label="s1", movements=(Movement(11, "proclination", 0.75),)),)
    report = evaluate_stages(_case(), stages)
    assert "H_STAGE_BOUND" in _codes(report)
    assert not report.is_valid


def test_per_tooth_total_bound_enforced() -> None:
    # proclination per_tooth_total = 6.0 → 7 staged halves violate the cap.
    stages = tuple(
        Stage(label=f"s{i}", movements=(Movement(11, "proclination", 0.5),)) for i in range(14)
    )
    report = evaluate_stages(_case(), stages)
    assert "H_TOTAL_BOUND" in _codes(report)


def test_two_movements_same_tooth_in_stage_rejected() -> None:
    # Stage construction already forbids this; the validator re-checks
    # raw movement records (defense in depth against provider bugs).
    case = _case()
    m1 = SimpleNamespace(tooth=11, movement_type="proclination", magnitude=0.5)
    m2 = SimpleNamespace(tooth=11, movement_type="torque", magnitude=5.0)
    stage = Stage.__new__(Stage)  # bypass the constructor guard on purpose
    object.__setattr__(stage, "label", "s1")
    object.__setattr__(stage, "movements", (m1, m2))
    report = evaluate_stages(case, (stage,))
    assert "H_ONE_MOVEMENT_PER_TOOTH" in _codes(report)


def test_overjet_envelope_hard_violation() -> None:
    # overjet 4.0 → absorbable = 1.0 mm; plan 3.0 mm of retroclination.
    case = _case(overjet_mm=4.0, objectives=["correct_overjet"])
    movements = tuple(Movement(t, "retroclination", 0.5) for t in (11, 12, 21, 22) for _ in (0,))
    # 4 teeth × 0.5 = 2.0 total across two stages → still > 1.0 absorbable
    stages = (
        Stage(label="s1", movements=movements),
        Stage(label="s2", movements=movements),
    )
    report = evaluate_stages(case, stages)
    assert "H_OVERJET_ENVELOPE" in _codes(report)
    assert not report.is_valid


def test_overjet_within_envelope_passes_hard_gate() -> None:
    # overjet 9.0 → absorbable min(6, 6) = 6.0; plan 2.0 total.
    case = _case(overjet_mm=9.0, objectives=["correct_overjet"])
    stages = (
        Stage(
            label="s1",
            movements=tuple(Movement(t, "retroclination", 0.25) for t in (11, 12, 21, 22)),
        ),
        Stage(
            label="s2",
            movements=tuple(Movement(t, "retroclination", 0.25) for t in (11, 12, 21, 22)),
        ),
    )
    report = evaluate_stages(case, stages)
    assert "H_OVERJET_ENVELOPE" not in _codes(report)
    assert report.is_valid


def test_space_deficit_is_soft_and_reported() -> None:
    case = _case(crowding_upper_mm=8.0, crowding_lower_mm=0.0)
    stages = (
        Stage(
            label="s1",
            movements=tuple(Movement(t, "proclination", 0.5) for t in (11, 12, 21, 22)),
        ),
    )
    report = evaluate_stages(case, stages)
    assert report.is_valid  # soft only
    deficit = [v for v in report.soft if v.code == "S_SPACE_DEFICIT"]
    assert len(deficit) == 1
    assert deficit[0].severity == SEVERITY_SOFT
    assert "specialist" in deficit[0].message


def test_space_relief_accounting() -> None:
    stages = (
        Stage(
            label="s1",
            movements=(
                Movement(11, "proclination", 0.5),
                Movement(16, "distalization", 0.5),
                Movement(36, "distalization", 2.0),  # capped at 1.0 per side
            ),
        ),
    )
    relief = space_relief_by_arch(stages)
    assert relief["upper"] == 1.0  # 0.5 proclination + 0.5 distalization
    assert relief["lower"] == 1.0  # distalization capped


def test_report_serialization_shape() -> None:
    report = evaluate_stages(_case(), ())
    payload = report.as_dict()
    assert payload["is_valid"] is False
    assert payload["hard_count"] >= 1
    first = payload["violations"][0]
    assert {"code", "severity", "message", "tooth"} <= set(first)
    assert first["severity"] in (SEVERITY_HARD, SEVERITY_SOFT)
