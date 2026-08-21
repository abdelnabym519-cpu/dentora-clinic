"""Pure domain rules for the agenda module.

This module intentionally has no FastAPI, Pydantic, SQLAlchemy, HTTP, or database
imports.  It owns the appointment state-machine invariants shared by every
adapter that schedules or transitions an appointment.
"""

from __future__ import annotations

from dataclasses import dataclass


VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"confirmed", "checked_in", "cancelled", "no_show"}),
    "confirmed": frozenset({"checked_in", "cancelled", "no_show"}),
    "checked_in": frozenset({"in_treatment", "cancelled"}),
    "in_treatment": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "no_show": frozenset(),
}


class InvalidTransitionError(ValueError):
    """Raised when a requested status transition is not allowed."""


class AlreadyInStateError(ValueError):
    """Raised when a transition targets the appointment's current state."""


class CabinetRequiredError(ValueError):
    """Raised when moving to ``in_treatment`` without a cabinet assigned."""


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    """Validated transition result, independent of persistence concerns."""

    from_status: str
    to_status: str


def validate_transition(
    current_status: str,
    to_status: str,
    *,
    has_cabinet: bool = True,
) -> TransitionDecision:
    """Validate the canonical appointment state transition.

    ``in_treatment`` requires a cabinet.  Terminal states have no outgoing
    transitions.  The function performs no I/O and is safe to reuse from API,
    background-job, booking, and future sync adapters.
    """
    if current_status == to_status:
        raise AlreadyInStateError(f"Appointment is already in state '{to_status}'")

    if to_status not in VALID_TRANSITIONS.get(current_status, frozenset()):
        raise InvalidTransitionError(
            f"Cannot transition appointment from '{current_status}' to '{to_status}'"
        )

    if to_status == "in_treatment" and not has_cabinet:
        raise CabinetRequiredError("A cabinet is required before starting treatment")

    return TransitionDecision(from_status=current_status, to_status=to_status)
