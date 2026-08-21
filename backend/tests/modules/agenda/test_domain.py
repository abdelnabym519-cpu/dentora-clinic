"""Pure-domain regression tests for Agenda."""

import pytest

from app.modules.agenda.domain import (
    AlreadyInStateError,
    CabinetRequiredError,
    InvalidTransitionError,
    VALID_TRANSITIONS,
    validate_transition,
)


def test_canonical_transition_graph_is_stable() -> None:
    assert VALID_TRANSITIONS == {
        "scheduled": frozenset({"confirmed", "checked_in", "cancelled", "no_show"}),
        "confirmed": frozenset({"checked_in", "cancelled", "no_show"}),
        "checked_in": frozenset({"in_treatment", "cancelled"}),
        "in_treatment": frozenset({"completed", "cancelled"}),
        "completed": frozenset(),
        "cancelled": frozenset(),
        "no_show": frozenset(),
    }


def test_valid_transition_returns_decision() -> None:
    decision = validate_transition("scheduled", "confirmed")
    assert decision.from_status == "scheduled"
    assert decision.to_status == "confirmed"


def test_same_state_is_rejected() -> None:
    with pytest.raises(AlreadyInStateError):
        validate_transition("scheduled", "scheduled")


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition("completed", "scheduled")


def test_treatment_requires_cabinet() -> None:
    with pytest.raises(CabinetRequiredError):
        validate_transition("checked_in", "in_treatment", has_cabinet=False)
