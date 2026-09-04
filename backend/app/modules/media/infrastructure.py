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
SERVICE_ASYNC_OPERATIONS: dict[str, tuple[str, ...]] = {
    name: tuple(
        operation
        for operation in SERVICE_OPERATIONS[name]
        if inspect.iscoroutinefunction(getattr(getattr(_legacy, name), operation))
    )
    for name in SERVICE_CLASS_NAMES
}
SERVICE_SYNC_OPERATIONS: dict[str, tuple[str, ...]] = {
    name: tuple(
        operation
        for operation in SERVICE_OPERATIONS[name]
        if operation not in SERVICE_ASYNC_OPERATIONS[name]
    )
    for name in SERVICE_CLASS_NAMES
}


def _resolve(target: str, operation: str):
    if target not in SERVICE_OPERATIONS or operation not in SERVICE_OPERATIONS[target]:
        raise AttributeError(f"Unknown Media operation: {target}.{operation}")
    return getattr(getattr(_legacy, target), operation)


class SqlAlchemyMediaGateway:
    """Dispatch Media application calls to the preserved outer implementation."""

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if operation not in SERVICE_ASYNC_OPERATIONS.get(target, ()):
            raise AttributeError(f"Media operation is not async: {target}.{operation}")
        return await _resolve(target, operation)(*args, **kwargs)

    def invoke_sync(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if operation not in SERVICE_SYNC_OPERATIONS.get(target, ()):
            raise AttributeError(f"Media operation is not synchronous: {target}.{operation}")
        return _resolve(target, operation)(*args, **kwargs)
