"""Outer Media adapter for the preserved SQLAlchemy implementation."""

from __future__ import annotations

import inspect
from typing import Any

from . import legacy as _legacy

SERVICE_CLASS_NAMES: tuple[str, ...] = (
    "DocumentService",
    "PhotoService",
    "AttachmentService",
)


def _static_operations(cls: type) -> tuple[str, ...]:
    return tuple(
        name
        for name, descriptor in vars(cls).items()
        if isinstance(descriptor, staticmethod) and not name.startswith("_")
    )


SERVICE_OPERATIONS: dict[str, tuple[str, ...]] = {
    name: _static_operations(getattr(_legacy, name)) for name in SERVICE_CLASS_NAMES
}


class SqlAlchemyMediaGateway:
    """Dispatch Media application calls to the preserved outer implementation."""

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if target not in SERVICE_OPERATIONS or operation not in SERVICE_OPERATIONS[target]:
            raise AttributeError(f"Unknown Media operation: {target}.{operation}")

        func = getattr(getattr(_legacy, target), operation)
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
