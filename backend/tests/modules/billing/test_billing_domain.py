from decimal import Decimal

from app.modules.billing.domain import (
    VALID_TRANSITIONS,
    calculate_item_totals,
    can_create_credit_note,
    can_edit,
    can_issue,
    can_record_payment,
    can_transition,
    can_void,
)


def test_invoice_item_totals_preserve_percentage_discount_math() -> None:
    totals = calculate_item_totals(
        unit_price=Decimal("100.00"),
        quantity=2,
        discount_type="percentage",
        discount_value=Decimal("10"),
        vat_rate=21,
    )
    assert totals.line_subtotal == Decimal("200.00")
    assert totals.line_discount == Decimal("20.00")
    assert totals.line_tax == Decimal("37.800")
    assert totals.line_total == Decimal("217.800")


def test_invoice_item_totals_preserve_absolute_discount_math() -> None:
    totals = calculate_item_totals(
        unit_price=Decimal("50.00"),
        quantity=1,
        discount_type="absolute",
        discount_value=Decimal("5.00"),
        vat_rate=0,
    )
    assert totals.line_subtotal == Decimal("50.00")
    assert totals.line_discount == Decimal("5.00")
    assert totals.line_tax == Decimal("0.00")
    assert totals.line_total == Decimal("45.00")


def test_invoice_workflow_graph_preserves_historical_contract() -> None:
    assert VALID_TRANSITIONS == {
        "draft": ("issued", "voided"),
        "issued": ("paid", "partial", "cancelled"),
        "partial": ("paid", "cancelled"),
        "paid": (),
        "cancelled": (),
        "voided": (),
    }
    assert can_transition("draft", "issued") is True
    assert can_transition("draft", "paid") is False


def test_invoice_workflow_predicates_preserve_rules() -> None:
    assert can_edit("draft") is True
    assert can_edit("issued") is False
    assert can_issue("draft", item_count=1) is True
    assert can_issue("draft", item_count=0) is False
    assert can_record_payment("partial") is True
    assert can_record_payment("paid") is False
    assert can_void("draft") is True
    assert can_void("issued") is False
    assert can_create_credit_note("paid", is_credit_note=False) is True
    assert can_create_credit_note("paid", is_credit_note=True) is False
