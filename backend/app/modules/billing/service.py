"""Compatibility composition boundary for Billing services.

Existing routers, tools, workflow code, tests, and cross-module consumers keep
the historical service call shape. Calls now enter a persistence-neutral
application boundary and then an outer adapter backed by the preserved legacy
SQLAlchemy implementation.
"""

from __future__ import annotations

from typing import Any

from . import legacy as _legacy
from .application import BillingApplication
from .infrastructure import (
    MODULE_OPERATIONS,
    SERVICE_CLASS_NAMES,
    SERVICE_OPERATIONS,
    SqlAlchemyBillingGateway,
)


async def _invoke(target: str, operation: str, *args: Any, **kwargs: Any) -> Any:
    app = BillingApplication(SqlAlchemyBillingGateway())
    return await app.invoke(target, operation, *args, **kwargs)


def _compat_method(target: str, operation: str):
    async def call(*args: Any, **kwargs: Any) -> Any:
        return await _invoke(target, operation, *args, **kwargs)

    call.__name__ = operation
    call.__qualname__ = operation
    call.__doc__ = f"Compatibility adapter for Billing operation ``{target}.{operation}``."
    return staticmethod(call)


def _compat_function(operation: str):
    async def call(*args: Any, **kwargs: Any) -> Any:
        return await _invoke("module", operation, *args, **kwargs)

    call.__name__ = operation
    call.__qualname__ = operation
    call.__doc__ = f"Compatibility adapter for Billing operation ``{operation}``."
    return call


class InvoiceNumberService:
    """Stable invoice-number facade."""


class InvoiceSeriesService:
    """Stable invoice-series facade."""


class InvoiceSeriesHistoryService:
    """Stable invoice-series history facade."""


class InvoiceHistoryService:
    """Stable invoice-history facade."""


class InvoiceItemService:
    """Stable invoice-item facade."""


class InvoiceService:
    """Stable invoice facade."""


class InvoicePaymentService:
    """Stable invoice-payment facade."""


_SERVICE_CLASSES: dict[str, type] = {
    "InvoiceNumberService": InvoiceNumberService,
    "InvoiceSeriesService": InvoiceSeriesService,
    "InvoiceSeriesHistoryService": InvoiceSeriesHistoryService,
    "InvoiceHistoryService": InvoiceHistoryService,
    "InvoiceItemService": InvoiceItemService,
    "InvoiceService": InvoiceService,
    "InvoicePaymentService": InvoicePaymentService,
}

for _class_name in SERVICE_CLASS_NAMES:
    _target_cls = _SERVICE_CLASSES[_class_name]
    for _operation in SERVICE_OPERATIONS[_class_name]:
        setattr(_target_cls, _operation, _compat_method(_class_name, _operation))

for _operation in MODULE_OPERATIONS:
    globals()[_operation] = _compat_function(_operation)


def __getattr__(name: str) -> Any:
    """Preserve any non-service public attribute from the historical module."""
    return getattr(_legacy, name)
