"""Compatibility composition boundary for Media services.

Existing routers, event handlers, tests, and cross-module consumers keep the
historical service call shape. Calls now enter a persistence-neutral
application boundary and then an outer adapter backed by the preserved legacy
SQLAlchemy implementation.
"""

from __future__ import annotations

from typing import Any

from . import legacy as _legacy
from .application import MediaApplication
from .infrastructure import (
    SERVICE_ASYNC_OPERATIONS,
    SERVICE_CLASS_NAMES,
    SERVICE_OPERATIONS,
    SqlAlchemyMediaGateway,
)


def _application() -> MediaApplication:
    return MediaApplication(SqlAlchemyMediaGateway())


async def _invoke(target: str, operation: str, *args: Any, **kwargs: Any) -> Any:
    return await _application().invoke(target, operation, *args, **kwargs)


def _invoke_sync(target: str, operation: str, *args: Any, **kwargs: Any) -> Any:
    return _application().invoke_sync(target, operation, *args, **kwargs)


def _compat_method(target: str, operation: str):
    if operation in SERVICE_ASYNC_OPERATIONS[target]:
        async def call(*args: Any, **kwargs: Any) -> Any:
            return await _invoke(target, operation, *args, **kwargs)
    else:
        def call(*args: Any, **kwargs: Any) -> Any:
            return _invoke_sync(target, operation, *args, **kwargs)

    call.__name__ = operation
    call.__qualname__ = operation
    call.__doc__ = f"Compatibility adapter for Media operation ``{target}.{operation}``."
    return staticmethod(call)


class DocumentService:
    """Stable document-service facade."""


class PhotoService:
    """Stable photo-service facade."""


class AttachmentService:
    """Stable attachment-service facade."""


_SERVICE_CLASSES: dict[str, type] = {
    "DocumentService": DocumentService,
    "PhotoService": PhotoService,
    "AttachmentService": AttachmentService,
}

for _class_name in SERVICE_CLASS_NAMES:
    _target_cls = _SERVICE_CLASSES[_class_name]
    for _operation in SERVICE_OPERATIONS[_class_name]:
        setattr(_target_cls, _operation, _compat_method(_class_name, _operation))


def __getattr__(name: str) -> Any:
    """Preserve any non-service public attribute from the historical module."""
    return getattr(_legacy, name)
