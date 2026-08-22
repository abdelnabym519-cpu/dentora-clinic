from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.billing.application import BillingApplication


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...], dict[str, Any]]] = []

    async def invoke(
        self,
        target: str,
        operation: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((target, operation, args, kwargs))
        return "delegated"


@pytest.mark.asyncio
async def test_non_domain_operation_delegates_to_gateway() -> None:
    gateway = FakeGateway()
    app = BillingApplication(gateway)

    result = await app.invoke("InvoiceService", "get_invoice", "db", "clinic", "invoice")

    assert result == "delegated"
    assert gateway.calls == [("InvoiceService", "get_invoice", ("db", "clinic", "invoice"), {})]


@pytest.mark.asyncio
async def test_item_total_calculation_stays_inside_application_domain() -> None:
    gateway = FakeGateway()
    app = BillingApplication(gateway)
    item = SimpleNamespace(
        unit_price=Decimal("80.00"),
        quantity=2,
        discount_type="percentage",
        discount_value=Decimal("25"),
        vat_rate=10,
        line_subtotal=None,
        line_discount=None,
        line_tax=None,
        line_total=None,
    )

    result = await app.invoke("InvoiceService", "calculate_item_totals", item)

    assert result is None
    assert item.line_subtotal == Decimal("160.00")
    assert item.line_discount == Decimal("40.00")
    assert item.line_tax == Decimal("12.00")
    assert item.line_total == Decimal("132.00")
    assert gateway.calls == []
