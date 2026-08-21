"""SQLAlchemy-backed outer adapter for Agenda application ports."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .domain import AlreadyInStateError, CabinetRequiredError, InvalidTransitionError
from .legacy import AlreadyInStateError as LegacyAlreadyInStateError
from .legacy import AppointmentService as LegacyAppointmentService
from .legacy import CabinetRequiredError as LegacyCabinetRequiredError
from .legacy import CabinetService as LegacyCabinetService
from .legacy import InvalidTransitionError as LegacyInvalidTransitionError
from .ports import AgendaGateway

CABINET_OPERATIONS = frozenset(
    {
        "list_cabinets",
        "get_cabinet",
        "get_by_name",
        "create_cabinet",
        "update_cabinet",
        "delete_cabinet",
    }
)

APPOINTMENT_OPERATIONS = frozenset(
    {
        "list_appointments",
        "list_status_events",
        "list_cabinet_events",
        "get_appointment",
        "validate_patient_access",
        "validate_professional_access",
        "validate_planned_items",
        "_resolve_cabinet",
        "_normalize_times",
        "create_appointment",
        "update_appointment",
        "cancel_appointment",
        "transition",
        "assign_cabinet",
        "update_appointment_treatment_note",
    }
)


class SqlAlchemyAgendaGateway(AgendaGateway):
    """Adapt the established SQLAlchemy implementation to ``AgendaGateway``.

    Keeping the proven persistence code in the outer layer preserves the stable
    database/API behavior while callers move through the new application port.
    Legacy domain exceptions are normalized so existing HTTP handlers keep
    catching the canonical inner-layer exception types.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        if operation in CABINET_OPERATIONS:
            method = getattr(LegacyCabinetService, operation)
        elif operation in APPOINTMENT_OPERATIONS:
            method = getattr(LegacyAppointmentService, operation)
        else:
            raise AttributeError(f"Unknown Agenda operation: {operation}")

        try:
            return await method(self._session, *args, **kwargs)
        except LegacyAlreadyInStateError as exc:
            raise AlreadyInStateError(str(exc)) from exc
        except LegacyCabinetRequiredError as exc:
            raise CabinetRequiredError(str(exc)) from exc
        except LegacyInvalidTransitionError as exc:
            raise InvalidTransitionError(str(exc)) from exc
