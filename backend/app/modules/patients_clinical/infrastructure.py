"""SQLAlchemy-backed outer adapter for patient clinical operations."""

from __future__ import annotations

from typing import Any

from . import legacy as _legacy


class SqlAlchemyPatientsClinicalGateway:
    """Delegate through the preserved SQLAlchemy implementation."""

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        target = getattr(_legacy.PatientsClinicalService, operation)
        return await target(*args, **kwargs)
