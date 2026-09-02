"""Domain unit tests — FDI helpers, movement/stage validation, sufficiency."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.orthodontic_planning.domain import (
    DentitionSnapshot,
    InsufficientDataError,
    Movement,
    PlannerCase,
    Stage,
    ToothSnapshot,
    arch_of,
    build_sufficiency,
    first_molars,
    is_valid_permanent_fdi,
    permanent_incisors,
)

from .helpers import complete_measurements, full_chart


class TestFdi:
    def test_valid_permanent_fdi(self) -> None:
        assert is_valid_permanent_fdi(11)
        assert is_valid_permanent_fdi(48)
        assert is_valid_permanent_fdi(36)

    @pytest.mark.parametrize("tooth", [0, 10, 19, 50, 91, 99, 5])
    def test_invalid_permanent_fdi(self, tooth: int) -> None:
        assert not is_valid_permanent_fdi(tooth)

    def test_arch(self) -> None:
        assert arch_of(16) == "upper"
        assert arch_of(21) == "upper"
        assert arch_of(33) == "lower"
        assert arch_of(46) == "lower"

    def test_arch_rejects_non_permanent(self) -> None:
        with pytest.raises(ValueError):
            arch_of(55)

    def test_incisors_and_molars(self) -> None:
        assert permanent_incisors("upper") == (11, 12, 21, 22)
        assert permanent_incisors("lower") == (31, 32, 41, 42)
        assert first_molars("upper") == (16, 26)
        assert first_molars("lower") == (36, 46)


class TestMovement:
    def test_valid_movement(self) -> None:
        movement = Movement(tooth=16, movement_type="distalization", magnitude=0.5)
        assert movement.as_dict() == {
            "tooth": 16,
            "movement_type": "distalization",
            "magnitude": 0.5,
        }

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(ValueError, match="Unknown movement type"):
            Movement(tooth=16, movement_type="teleportation", magnitude=1.0)

    def test_rejects_non_positive_magnitude(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Movement(tooth=16, movement_type="distalization", magnitude=0.0)

    def test_rejects_invalid_fdi(self) -> None:
        with pytest.raises(ValueError, match="FDI"):
            Movement(tooth=52, movement_type="distalization", magnitude=0.5)


class TestStage:
    def test_rejects_two_movements_same_tooth(self) -> None:
        with pytest.raises(ValueError, match="one movement per tooth"):
            Stage(
                label="s1",
                movements=(
                    Movement(tooth=11, movement_type="proclination", magnitude=0.5),
                    Movement(tooth=11, movement_type="torque", magnitude=5.0),
                ),
            )

    def test_allows_same_tooth_across_stages(self) -> None:
        Stage(
            label="s1",
            movements=(Movement(tooth=11, movement_type="proclination", magnitude=0.5),),
        )
        Stage(
            label="s2",
            movements=(Movement(tooth=11, movement_type="proclination", magnitude=0.5),),
        )


class TestSnapshot:
    def test_present_and_deciduous(self) -> None:
        snapshot = full_chart(missing=(16,), rotated=(11,), deciduous=(55,))
        assert snapshot.is_plannable_tooth(11)
        assert not snapshot.is_plannable_tooth(16)  # missing
        assert not snapshot.is_plannable_tooth(55)  # deciduous
        assert snapshot.charted_permanent_count() == 31
        assert snapshot.deciduous_present() == (55,)
        assert snapshot.get(16) is not None  # known but missing
        assert snapshot.get(99) is None  # unknown

    def test_empty_snapshot(self) -> None:
        empty = DentitionSnapshot()
        assert empty.charted_permanent_count() == 0
        assert not empty.is_plannable_tooth(11)


class TestSufficiency:
    def test_complete_case_is_plannable(self) -> None:
        report = build_sufficiency(measurements=complete_measurements(), dentition=full_chart())
        assert report["is_plannable"] is True
        assert report["missing"] == []
        assert report["score"] == 1.0
        assert report["charted_permanent"] == 32

    def test_under_charted_odontogram_fails(self) -> None:
        sparse = DentitionSnapshot(
            teeth=tuple(
                ToothSnapshot(tooth_number=t, dentition="permanent", present=True)
                for t in (11, 12, 21, 22, 31, 32, 41, 42, 16, 26)
            )
        )
        report = build_sufficiency(measurements=complete_measurements(), dentition=sparse)
        assert report["is_plannable"] is False
        assert any("odontogram" in m for m in report["missing"])

    def test_missing_measurements_listed(self) -> None:
        partial = complete_measurements()
        del partial["overjet_mm"]
        del partial["skeletal_pattern"]
        report = build_sufficiency(measurements=partial, dentition=full_chart())
        assert report["is_plannable"] is False
        assert set(report["missing"]) == {"overjet_mm", "skeletal_pattern"}
        assert report["score"] == round(8 / 10, 4)


class TestPlannerCase:
    def _case(self, measurements: dict) -> PlannerCase:
        sufficiency = build_sufficiency(measurements=measurements, dentition=full_chart())
        return PlannerCase(
            patient_id=uuid4(),
            objectives=tuple(measurements.get("objectives", ())),
            dentition=full_chart(),
            sufficiency=sufficiency,
            posterior_crossbite=False,
            **{
                k: v
                for k, v in measurements.items()
                if k not in ("objectives", "posterior_crossbite")
            },
        )

    def test_require_plannable_passes(self) -> None:
        self._case(complete_measurements()).require_plannable()

    def test_require_plannable_raises_with_missing_list(self) -> None:
        partial = complete_measurements()
        partial["overjet_mm"] = None
        partial["objectives"] = []
        case = self._case(partial)
        with pytest.raises(InsufficientDataError) as exc:
            case.require_plannable()
        assert "overjet_mm" in exc.value.missing
        assert any("objectives" in m for m in exc.value.missing)
