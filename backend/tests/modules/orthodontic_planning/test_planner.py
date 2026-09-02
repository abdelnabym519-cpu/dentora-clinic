"""Planner + provider-registry tests (no DB, no external model).

Covers: deterministic output, bound compliance, self-validation, fail-
closed behaviors (insufficient data, unknown provider), scoring, and
provider registration (the seam a future learned policy plugs into).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.orthodontic_planning.constraints import evaluate_stages
from app.modules.orthodontic_planning.domain import (
    DentitionSnapshot,
    InsufficientDataError,
    Movement,
    PlannerCase,
    Stage,
    ToothSnapshot,
)
from app.modules.orthodontic_planning.planner import (
    PROVIDER_NAME,
    HeuristicPlanner,
    PlanSuggestion,
    ProviderRegistryError,
    ProviderUnavailableError,
    get_provider,
    register_provider,
    score_proposal,
)

from .helpers import complete_measurements, full_chart


def _case(**overrides) -> PlannerCase:
    from app.modules.orthodontic_planning.domain import build_sufficiency

    dentition = full_chart(
        missing=overrides.pop("missing", overrides.pop("_missing", ())),
        rotated=overrides.pop("rotated", overrides.pop("_rotated", ())),
        displaced=overrides.pop("displaced", overrides.pop("_displaced", ())),
        deciduous=overrides.pop("deciduous", overrides.pop("_deciduous", ())),
        absent=overrides.pop("absent", overrides.pop("_absent", ())),
    )
    measurements = complete_measurements(**overrides)
    return PlannerCase(
        patient_id=uuid4(),
        objectives=tuple(measurements.get("objectives", ())),
        dentition=dentition,
        sufficiency=build_sufficiency(measurements=measurements, dentition=dentition),
        posterior_crossbite=measurements.get("posterior_crossbite", False),
        **{k: v for k, v in measurements.items() if k not in ("objectives", "posterior_crossbite")},
    )


class TestHeuristicPlanner:
    def test_is_deterministic(self) -> None:
        case = _case(rotated=(11, 21), displaced=(33,))
        first = HeuristicPlanner().propose_plan(case)
        second = HeuristicPlanner().propose_plan(case)
        assert first.stages == second.stages
        assert first.score == second.score
        assert first.confidence == second.confidence
        assert first.rationale == second.rationale
        assert first.uncertainty == second.uncertainty

    def test_output_respects_all_hard_bounds(self) -> None:
        case = _case(
            rotated=(11, 12, 21, 22, 31, 32, 41, 42),
            displaced=(13, 23, 33, 43),
            crowding_upper_mm=4.0,
            crowding_lower_mm=4.0,
            overjet_mm=8.0,
            objectives=["align", "space_management", "correct_overjet"],
        )
        suggestion = HeuristicPlanner().propose_plan(case)
        report = evaluate_stages(case, suggestion.stages)
        # The reference policy must NEVER violate its own safety gate.
        assert report.is_valid, [v.code for v in report.violations]
        assert not report.hard

    def test_insufficient_data_raises_with_missing_list(self) -> None:
        case = _case()
        sparse_dentition = DentitionSnapshot(
            teeth=tuple(
                ToothSnapshot(tooth_number=t, dentition="permanent", present=True)
                for t in (11, 12, 21, 22, 31, 32, 41, 42, 16, 26)
            )
        )
        sparse = PlannerCase(
            patient_id=case.patient_id,
            skeletal_pattern=case.skeletal_pattern,
            growth_stage=case.growth_stage,
            overjet_mm=case.overjet_mm,
            overbite_mm=case.overbite_mm,
            crowding_upper_mm=case.crowding_upper_mm,
            crowding_lower_mm=case.crowding_lower_mm,
            molar_relation_left=case.molar_relation_left,
            molar_relation_right=case.molar_relation_right,
            canine_relation_left=case.canine_relation_left,
            canine_relation_right=case.canine_relation_right,
            posterior_crossbite=False,
            objectives=case.objectives,
            dentition=sparse_dentition,
            sufficiency={
                "is_plannable": False,
                "missing": ["odontogram_charted_permanent_teeth(<20)"],
                "score": 1.0,
                "charted_permanent": 10,
            },
        )
        with pytest.raises(InsufficientDataError) as exc:
            HeuristicPlanner().propose_plan(sparse)
        assert exc.value.missing

    def test_missing_objectives_fail_closed(self) -> None:
        case = _case()
        empty = PlannerCase(
            patient_id=case.patient_id,
            skeletal_pattern=case.skeletal_pattern,
            growth_stage=case.growth_stage,
            overjet_mm=case.overjet_mm,
            overbite_mm=case.overbite_mm,
            crowding_upper_mm=case.crowding_upper_mm,
            crowding_lower_mm=case.crowding_lower_mm,
            molar_relation_left=case.molar_relation_left,
            molar_relation_right=case.molar_relation_right,
            canine_relation_left=case.canine_relation_left,
            canine_relation_right=case.canine_relation_right,
            posterior_crossbite=False,
            objectives=(),
            dentition=case.dentition,
            sufficiency=case.sufficiency,
        )
        with pytest.raises(InsufficientDataError):
            HeuristicPlanner().propose_plan(empty)

    def test_stages_within_plan_horizon(self) -> None:
        case = _case(
            rotated=tuple(q * 10 + p for q in (1, 2, 3, 4) for p in range(1, 9)),
            crowding_upper_mm=5.0,
            crowding_lower_mm=5.0,
        )
        suggestion = HeuristicPlanner().propose_plan(case)
        assert 1 <= len(suggestion.stages) <= 30

    def test_confidence_capped_and_scaled_by_sufficiency(self) -> None:
        suggestion = HeuristicPlanner().propose_plan(_case())
        assert 0.0 <= suggestion.confidence <= 0.9
        assert suggestion.confidence == pytest.approx(0.9)

    def test_uncertainty_notes_for_mixed_dentition_and_adult(self) -> None:
        suggestion = HeuristicPlanner().propose_plan(
            _case(_deciduous=(55,), growth_stage="adult", skeletal_pattern="class_ii")
        )
        joined = " | ".join(suggestion.uncertainty)
        assert "Mixed dentition" in joined
        assert "growth modification" in joined
        # Deterministic reference policy always discloses its nature.
        assert "Deterministic reference policy" in joined

    def test_crossbite_objective_flagged(self) -> None:
        suggestion = HeuristicPlanner().propose_plan(
            _case(objectives=["align", "correct_crossbite"], posterior_crossbite=True)
        )
        assert any("Transverse" in note for note in suggestion.uncertainty)

    def test_score_within_range(self) -> None:
        suggestion = HeuristicPlanner().propose_plan(_case())
        assert 0.0 <= suggestion.score <= 1.0

    def test_provider_metadata(self) -> None:
        planner = HeuristicPlanner()
        suggestion = planner.propose_plan(_case())
        assert suggestion.provider == PROVIDER_NAME == planner.name
        assert suggestion.provider_version


class TestScoring:
    def test_score_prefers_full_alignment_within_envelope(self) -> None:
        relief_stages = (
            Stage(
                label="s1",
                movements=tuple(Movement(t, "proclination", 0.25) for t in (11, 12, 21, 22)),
            ),
        )
        case_low = _case(crowding_upper_mm=0.5, crowding_lower_mm=0.0)
        case_high = _case(crowding_upper_mm=15.0, crowding_lower_mm=0.0)
        score_low, ratio_low, env_low = score_proposal(case_low, relief_stages)
        score_high, ratio_high, env_high = score_proposal(case_high, relief_stages)
        assert ratio_low == 1.0
        assert ratio_high < 1.0
        assert env_low and not env_high
        assert score_low > score_high

    def test_score_is_deterministic(self) -> None:
        case = _case()
        assert score_proposal(case, ()) == score_proposal(case, ())


class FakeLearnedPolicy:
    """A stand-in for a future ML/RL provider (used by registry tests)."""

    name = "fake_learned"
    version = "0.0.1"

    def __init__(self) -> None:
        self.calls = 0

    def propose_plan(self, case: PlannerCase) -> PlanSuggestion:
        self.calls += 1
        return PlanSuggestion(
            stages=(Stage(label="s1", movements=(Movement(11, "proclination", 0.5),)),),
            provider=self.name,
            provider_version=self.version,
            score=0.5,
            confidence=0.4,
            uncertainty=("fake policy",),
            rationale="fake",
        )


class TestProviderRegistry:
    def test_default_provider_resolves_heuristic(self) -> None:
        provider = get_provider(None)
        assert provider.name == PROVIDER_NAME

    def test_unknown_provider_fails_closed(self) -> None:
        with pytest.raises(ProviderUnavailableError, match="unknown_provider_xyz"):
            get_provider("unknown_provider_xyz")

    def test_empty_setting_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "ORTHO_PLANNING_PROVIDER", "")
        with pytest.raises(ProviderUnavailableError, match="No orthodontic planning provider"):
            get_provider(None)

    def test_register_and_resolve_custom_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import settings

        register_provider("fake_learned", FakeLearnedPolicy)
        monkeypatch.setattr(settings, "ORTHO_PLANNING_PROVIDER", "fake_learned")
        provider = get_provider(None)
        assert isinstance(provider, FakeLearnedPolicy)
        suggestion = provider.propose_plan(_case())
        assert suggestion.provider == "fake_learned"

    def test_broken_factory_fails_closed(self) -> None:
        def broken() -> object:
            raise RuntimeError("boom")

        register_provider("broken_provider", broken)  # type: ignore[arg-type]
        with pytest.raises(ProviderUnavailableError, match="failed to initialize"):
            get_provider("broken_provider")

    def test_duplicate_registration_is_idempotent(self) -> None:
        register_provider("fake_learned", FakeLearnedPolicy)
        register_provider("fake_learned", FakeLearnedPolicy)

    def test_invalid_registration_rejected(self) -> None:
        with pytest.raises(ProviderRegistryError):
            register_provider("", FakeLearnedPolicy)
        with pytest.raises(ProviderRegistryError):
            register_provider("x", "not-callable")  # type: ignore[arg-type]

    def test_plan_suggestion_validates_ranges(self) -> None:
        with pytest.raises(ValueError):
            PlanSuggestion(
                stages=(),
                provider="p",
                provider_version="v",
                score=1.5,
                confidence=0.5,
            )
