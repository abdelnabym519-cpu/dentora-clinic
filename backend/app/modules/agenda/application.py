"""Persistence-neutral Agenda application boundary."""

from __future__ import annotations

from typing import Any

from .domain import validate_transition
from .ports import AgendaGateway


class AgendaApplication:
    """Coordinate Agenda use cases through an injected outer gateway.

    The public HTTP/service contract remains unchanged while the application
    boundary is independent from SQLAlchemy and FastAPI. Domain rules that can
    be evaluated without I/O are enforced here before persistence.
    """

    def __init__(self, gateway: AgendaGateway) -> None:
        self._gateway = gateway

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        if operation == "transition":
            appointment = args[0] if args else kwargs["appointment"]
            if len(args) > 1:
                to_status = args[1]
            else:
                to_status = kwargs["to_status"]
            validate_transition(
                appointment.status,
                to_status,
                has_cabinet=getattr(appointment, "cabinet_id", None) is not None,
            )
        elif operation == "cancel_appointment":
            appointment = args[0] if args else kwargs["appointment"]
            # Historical behavior: cancelling an already-cancelled appointment
            # is an idempotent no-op, not an AlreadyInStateError.
            if appointment.status != "cancelled":
                validate_transition(
                    appointment.status,
                    "cancelled",
                    has_cabinet=getattr(appointment, "cabinet_id", None) is not None,
                )

        return await self._gateway.invoke(operation, *args, **kwargs)
