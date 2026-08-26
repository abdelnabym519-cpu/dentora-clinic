"""Compatibility composition boundary for Agenda services.

The stable ``AppointmentService`` / ``CabinetService`` call shape is preserved
for existing routers, tools, tests, and cross-module consumers.  Each call is
composed through the persistence-neutral application boundary and an injected
SQLAlchemy gateway; framework/database details therefore stay outside the
Agenda inner layers.
"""

from __future__ import annotations

from typing import Any

from . import domain as _domain
from .application import AgendaApplication
from .infrastructure import (
    APPOINTMENT_OPERATIONS,
    CABINET_OPERATIONS,
    SqlAlchemyAgendaGateway,
)

# Preserve the historical exception import surface used by routers/tools while
# the canonical exception types live in the pure domain layer.
AlreadyInStateError = _domain.AlreadyInStateError
CabinetRequiredError = _domain.CabinetRequiredError
InvalidTransitionError = _domain.InvalidTransitionError

# Preserve the historical outward value shape (``set`` values) while the
# canonical immutable graph lives in ``domain.py``.
VALID_TRANSITIONS: dict[str, set[str]] = {
    state: set(targets) for state, targets in _domain.VALID_TRANSITIONS.items()
}


async def _invoke(operation: str, db: Any, *args: Any, **kwargs: Any) -> Any:
    app = AgendaApplication(SqlAlchemyAgendaGateway(db))
    return await app.invoke(operation, *args, **kwargs)


def _compat_method(operation: str):
    async def call(db: Any, *args: Any, **kwargs: Any) -> Any:
        return await _invoke(operation, db, *args, **kwargs)

    call.__name__ = operation
    call.__qualname__ = operation
    call.__doc__ = f"Compatibility adapter for Agenda operation ``{operation}``."
    return staticmethod(call)


class AppointmentService:
    """Stable service facade composed through ``AgendaApplication``."""


class CabinetService:
    """Stable cabinet facade composed through ``AgendaApplication``."""


for _operation in APPOINTMENT_OPERATIONS:
    setattr(AppointmentService, _operation, _compat_method(_operation))

for _operation in CABINET_OPERATIONS:
    setattr(CabinetService, _operation, _compat_method(_operation))


del _operation
