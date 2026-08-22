"""Pure Billing domain rules.

This module deliberately has no dependency on FastAPI, SQLAlchemy, the event
bus, or ORM models.  It contains only deterministic invoice calculations and
workflow predicates that can be evaluated without I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("issued", "voided"),
    "issued": ("paid", "partial", "cancelled"),
    "partial": ("paid", "cancelled"),
    "paid": (),
    "cancelled": (),
    "voided": (),
}


@dataclass(frozen=True, slots=True)
class InvoiceItemTotals:
    """Deterministic monetary result for one invoice item."""

    line_subtotal: Decimal
    line_discount: Decimal
    line_tax: Decimal
    line_total: Decimal


def calculate_item_totals(
    *,
    unit_price: Decimal,
    quantity: int | Decimal,
    discount_type: str | None,
    discount_value: Decimal | None,
    vat_rate: Decimal | float | int,
) -> InvoiceItemTotals:
    """Calculate invoice-line totals using the historical Billing rules."""
    line_subtotal = unit_price * quantity
    line_discount = Decimal("0.00")

    if discount_type and discount_value:
        if discount_type == "percentage":
            line_discount = line_subtotal * discount_value / Decimal("100")
        else:
            line_discount = discount_value

    taxable_amount = line_subtotal - line_discount
    line_tax = taxable_amount * Decimal(str(vat_rate)) / Decimal("100")
    line_total = taxable_amount + line_tax
    return InvoiceItemTotals(
        line_subtotal=line_subtotal,
        line_discount=line_discount,
        line_tax=line_tax,
        line_total=line_total,
    )


def can_transition(current_status: str, new_status: str) -> bool:
    """Return whether the invoice state machine permits a transition."""
    return new_status in VALID_TRANSITIONS.get(current_status, ())


def can_edit(status: str) -> bool:
    return status == "draft"


def can_issue(status: str, *, item_count: int) -> bool:
    return status == "draft" and item_count > 0


def can_record_payment(status: str) -> bool:
    return status in {"issued", "partial"}


def can_void(status: str) -> bool:
    return status == "draft"


def can_create_credit_note(status: str, *, is_credit_note: bool) -> bool:
    return not is_credit_note and status in {"issued", "partial", "paid"}
