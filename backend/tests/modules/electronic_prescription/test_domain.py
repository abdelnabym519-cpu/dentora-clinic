from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.electronic_prescription import ElectronicPrescriptionModule
from app.modules.electronic_prescription.domain import (
    MedicationItem,
    Prescription,
    PrescriptionError,
    PrescriptionStatus,
)

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def item() -> MedicationItem:
    return MedicationItem(
        medication_name="Amoxicillin",
        strength="500 mg",
        dose="1 capsule",
        frequency="every 8 hours",
        duration="5 days",
        route="oral",
        instructions="after food",
        quantity=15,
        quantity_unit="capsule",
    )


def draft(*, doctor_id=None, items=None) -> Prescription:
    return Prescription(
        id=uuid4(),
        tenant_id=uuid4(),
        clinic_id=uuid4(),
        patient_id=uuid4(),
        doctor_id=doctor_id or uuid4(),
        identifier="RX-20260825-ABCDEF123456",
        status=PrescriptionStatus.DRAFT,
        items=tuple(items if items is not None else [item()]),
        created_at=NOW,
        updated_at=NOW,
    )


def test_issue_makes_prescription_immutable() -> None:
    issued = draft().issue(now=NOW)
    assert issued.status is PrescriptionStatus.ISSUED
    assert issued.issued_at == NOW
    with pytest.raises(PrescriptionError, match="immutable"):
        issued.update_draft(patient_id=issued.patient_id, items=(item(),), now=NOW)


def test_empty_draft_cannot_be_issued() -> None:
    with pytest.raises(PrescriptionError, match="at least one medication"):
        draft(items=[]).issue(now=NOW)


def test_cancel_only_applies_to_draft_and_requires_reason() -> None:
    rx = draft()
    with pytest.raises(PrescriptionError, match="reason is required"):
        rx.cancel(reason=" ", now=NOW)
    cancelled = rx.cancel(reason="duplicate", now=NOW)
    assert cancelled.status is PrescriptionStatus.CANCELLED
    with pytest.raises(PrescriptionError, match="only draft"):
        cancelled.cancel(reason="again", now=NOW)


def test_void_only_applies_to_issued_and_requires_reason() -> None:
    rx = draft()
    with pytest.raises(PrescriptionError, match="only issued"):
        rx.void(reason="error", now=NOW)
    issued = rx.issue(now=NOW)
    with pytest.raises(PrescriptionError, match="reason is required"):
        issued.void(reason="", now=NOW)
    assert issued.void(reason="entered in error", now=NOW).status is PrescriptionStatus.VOIDED


def test_only_prescribing_doctor_can_modify() -> None:
    owner = uuid4()
    rx = draft(doctor_id=owner)
    rx.assert_owned_by(owner)
    with pytest.raises(PrescriptionError, match="prescribing doctor"):
        rx.assert_owned_by(uuid4())


def test_medication_validation_rejects_invalid_quantity() -> None:
    invalid = MedicationItem(
        medication_name="Drug",
        dose="1",
        frequency="daily",
        duration="1 day",
        route="oral",
        quantity=0,
    )
    with pytest.raises(PrescriptionError, match="quantity"):
        invalid.validated()


def test_manifest_rbac_is_clinically_scoped() -> None:
    manifest = ElectronicPrescriptionModule.manifest
    assert manifest["role_permissions"]["admin"] == ["*"]
    assert set(manifest["role_permissions"]["dentist"]) == {
        "read",
        "write",
        "issue",
        "cancel",
        "void",
        "audit",
    }
    assert manifest["role_permissions"]["receptionist"] == []
