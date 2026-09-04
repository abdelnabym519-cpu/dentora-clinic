"""Outer Billing adapters for the existing SQLAlchemy implementation."""

from __future__ import annotations

import inspect
from typing import Any

from . import legacy as _legacy
from . import legacy_workflow as _legacy_workflow

SERVICE_CLASS_NAMES: tuple[str, ...] = (
    "InvoiceNumberService",
    "InvoiceSeriesService",
    "InvoiceSeriesHistoryService",
    "InvoiceHistoryService",
    "InvoiceItemService",
    "InvoiceService",
    "InvoicePaymentService",
)

MODULE_OPERATIONS: tuple[str, ...] = (
    "compute_paid_summary",
    "compute_paid_summaries_for_invoices",
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

WORKFLOW_OPERATIONS: tuple[str, ...] = _static_operations(_legacy_workflow.InvoiceWorkflowService)
WORKFLOW_ASYNC_OPERATIONS: tuple[str, ...] = tuple(
    name
    for name in WORKFLOW_OPERATIONS
    if inspect.iscoroutinefunction(getattr(_legacy_workflow.InvoiceWorkflowService, name))
)
WORKFLOW_SYNC_OPERATIONS: tuple[str, ...] = tuple(
    name for name in WORKFLOW_OPERATIONS if name not in WORKFLOW_ASYNC_OPERATIONS
)


class SqlAlchemyBillingGateway:
    """Dispatch application calls to the preserved outer implementation."""

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if target == "module":
            if operation not in MODULE_OPERATIONS:
                raise AttributeError(f"Unknown Billing operation: {target}.{operation}")
            func = getattr(_legacy, operation)
        elif target == "InvoiceWorkflowService":
            if operation not in WORKFLOW_OPERATIONS:
                raise AttributeError(f"Unknown Billing operation: {target}.{operation}")
            func = getattr(_legacy_workflow.InvoiceWorkflowService, operation)
        elif target in SERVICE_OPERATIONS and operation in SERVICE_OPERATIONS[target]:
            func = getattr(getattr(_legacy, target), operation)
        else:
            raise AttributeError(f"Unknown Billing operation: {target}.{operation}")

        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
