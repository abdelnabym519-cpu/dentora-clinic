"""DB-free application tests for Agenda dependency inversion."""

from dataclasses import dataclass
from typing import Any

import pytest

from app.modules.agenda.application import AgendaApplication
from app.modules.agenda.domain import InvalidTransitionError


class FakeGateway:
    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((operation, args, kwargs))
        return self.result


@dataclass
class AppointmentStub:
    status: str
    cabinet_id: str | None = "cabinet-1"
    cabinet: str | None = "Room 1"


@pytest.mark.asyncio
async def test_non_domain_operation_delegates_to_gateway() -> None:
    gateway = FakeGateway(result=([], 0))
    app = AgendaApplication(gateway)

    result = await app.invoke("list_appointments", "clinic")

    assert result == ([], 0)
    assert gateway.calls == [("list_appointments", ("clinic",), {})]


@pytest.mark.asyncio
async def test_valid_transition_is_delegated_after_domain_validation() -> None:
    gateway = FakeGateway(result="updated")
    app = AgendaApplication(gateway)
    appointment = AppointmentStub(status="checked_in")

    result = await app.invoke("transition", appointment, "in_treatment", note="start")

    assert result == "updated"
    assert gateway.calls == [("transition", (appointment, "in_treatment"), {"note": "start"})]


@pytest.mark.asyncio
async def test_invalid_transition_never_reaches_gateway() -> None:
    gateway = FakeGateway()
    app = AgendaApplication(gateway)
    appointment = AppointmentStub(status="completed")

    with pytest.raises(InvalidTransitionError):
        await app.invoke("transition", appointment, "scheduled")

    assert gateway.calls == []


@pytest.mark.asyncio
async def test_cancel_uses_same_domain_state_machine() -> None:
    gateway = FakeGateway(result="cancelled")
    app = AgendaApplication(gateway)
    appointment = AppointmentStub(status="confirmed")

    assert await app.invoke("cancel_appointment", appointment) == "cancelled"
    assert gateway.calls[0][0] == "cancel_appointment"
