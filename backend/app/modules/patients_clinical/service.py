"""Compatibility composition boundary for patient clinical services.

Routers and existing consumers retain the historical static service API while
calls cross a persistence-neutral application boundary before reaching the
preserved SQLAlchemy implementation in ``legacy.py``.
"""

from __future__ import annotations

import inspect
from typing import Any

from . import legacy as _legacy
from .application import PatientsClinicalApplication
from .infrastructure import SqlAlchemyPatientsClinicalGateway


def _application() -> PatientsClinicalApplication:
    return PatientsClinicalApplication(SqlAlchemyPatientsClinicalGateway())


def _compat_method(operation: str):
    async def call(*args: Any, **kwargs: Any) -> Any:
        return await _application().invoke(operation, *args, **kwargs)

    call.__name__ = operation
    call.__qualname__ = operation
    call.__doc__ = f"Compatibility adapter for PatientsClinicalService.{operation}."
    return staticmethod(call)


class PatientsClinicalService:
    """Stable facade for all historical asynchronous clinical operations."""


for _operation in vars(_legacy.PatientsClinicalService):
    if _operation.startswith("_"):
        continue
    _target = getattr(_legacy.PatientsClinicalService, _operation)
    if inspect.iscoroutinefunction(_target):
        setattr(PatientsClinicalService, _operation, _compat_method(_operation))


def __getattr__(name: str) -> Any:
    """Preserve non-service public attributes from the historical module."""
    return getattr(_legacy, name)
