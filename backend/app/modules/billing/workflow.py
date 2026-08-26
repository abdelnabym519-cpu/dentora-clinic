"""Compatibility composition boundary for the Billing invoice workflow."""

from __future__ import annotations

from typing import Any

from . import domain as _domain
from . import legacy_workflow as _legacy_workflow
from .application import BillingApplication
from .infrastructure import WORKFLOW_ASYNC_OPERATIONS, SqlAlchemyBillingGateway

InvoiceWorkflowError = _legacy_workflow.InvoiceWorkflowError
VALID_TRANSITIONS: dict[str, list[str]] = {
    state: list(targets) for state, targets in _domain.VALID_TRANSITIONS.items()
}


async def _invoke(operation: str, *args: Any, **kwargs: Any) -> Any:
    app = BillingApplication(SqlAlchemyBillingGateway())
    return await app.invoke("InvoiceWorkflowService", operation, *args, **kwargs)


def _compat_async_method(operation: str):
    async def call(*args: Any, **kwargs: Any) -> Any:
        return await _invoke(operation, *args, **kwargs)

    call.__name__ = operation
    call.__qualname__ = operation
    call.__doc__ = f"Compatibility adapter for Billing workflow operation ``{operation}``."
    return staticmethod(call)


class InvoiceWorkflowService:
    """Stable workflow facade with pure predicates in the domain layer."""

    @staticmethod
    def can_transition(current_status: str, new_status: str) -> bool:
        return _domain.can_transition(current_status, new_status)

    @staticmethod
    def can_edit(invoice: Any) -> bool:
        return _domain.can_edit(invoice.status)

    @staticmethod
    def can_issue(invoice: Any) -> bool:
        return _domain.can_issue(invoice.status, item_count=len(invoice.items))

    @staticmethod
    def can_record_payment(invoice: Any) -> bool:
        return _domain.can_record_payment(invoice.status)

    @staticmethod
    def can_void(invoice: Any) -> bool:
        return _domain.can_void(invoice.status)

    @staticmethod
    def can_create_credit_note(invoice: Any) -> bool:
        return _domain.can_create_credit_note(
            invoice.status,
            is_credit_note=invoice.credit_note_for_id is not None,
        )


for _operation in WORKFLOW_ASYNC_OPERATIONS:
    setattr(InvoiceWorkflowService, _operation, _compat_async_method(_operation))


def __getattr__(name: str) -> Any:
    """Preserve any non-workflow public attribute from the historical module."""
    return getattr(_legacy_workflow, name)
