"""Persistence-neutral Billing application boundary."""

from __future__ import annotations

from typing import Any

from .domain import calculate_item_totals
from .ports import BillingGateway


class BillingApplication:
    """Coordinate Billing use cases through an injected outer gateway."""

    def __init__(self, gateway: BillingGateway) -> None:
        self._gateway = gateway

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        # This rule is fully deterministic, so keep it inside the inner layer
        # instead of crossing the SQLAlchemy adapter. The mutable object is
        # treated structurally; the application layer does not import its ORM
        # type and preserves the historical in-place result contract.
        if target == "InvoiceService" and operation == "calculate_item_totals":
            item = args[0] if args else kwargs["item"]
            totals = calculate_item_totals(
                unit_price=item.unit_price,
                quantity=item.quantity,
                discount_type=item.discount_type,
                discount_value=item.discount_value,
                vat_rate=item.vat_rate,
            )
            item.line_subtotal = totals.line_subtotal
            item.line_discount = totals.line_discount
            item.line_tax = totals.line_tax
            item.line_total = totals.line_total
            return None

        return await self._gateway.invoke(target, operation, *args, **kwargs)
