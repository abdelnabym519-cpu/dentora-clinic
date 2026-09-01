"""Pure Electronic Prescription domain model and lifecycle rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PrescriptionError(ValueError):
    """Base domain error exposed as a validation conflict by the API."""


class PrescriptionStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    CANCELLED = "cancelled"
    VOIDED = "voided"


@dataclass(frozen=True, slots=True)
class MedicationItem:
    medication_name: str
    dose: str
    frequency: str
    duration: str
    route: str
    quantity: int
    instructions: str | None = None
    strength: str | None = None
    quantity_unit: str | None = None
    id: UUID | None = None

    def validated(self) -> MedicationItem:
        required = {
            "medication_name": self.medication_name,
            "dose": self.dose,
            "frequency": self.frequency,
            "duration": self.duration,
            "route": self.route,
        }
        for field, value in required.items():
            if not value.strip():
                raise PrescriptionError(f"{field} is required")
        if self.quantity <= 0:
            raise PrescriptionError("quantity must be greater than zero")
        return self


@dataclass(frozen=True, slots=True)
class Prescription:
    id: UUID
    tenant_id: UUID
    clinic_id: UUID
    patient_id: UUID
    doctor_id: UUID
    identifier: str
    status: PrescriptionStatus
    items: tuple[MedicationItem, ...]
    created_at: datetime
    updated_at: datetime
    issued_at: datetime | None = None
    cancelled_at: datetime | None = None
    voided_at: datetime | None = None
    cancel_reason: str | None = None
    void_reason: str | None = None

    def assert_owned_by(self, actor_id: UUID) -> None:
        if self.doctor_id != actor_id:
            raise PrescriptionError("only the prescribing doctor may modify this prescription")

    def update_draft(
        self,
        *,
        patient_id: UUID,
        items: tuple[MedicationItem, ...],
        now: datetime,
    ) -> Prescription:
        if self.status is not PrescriptionStatus.DRAFT:
            raise PrescriptionError("issued or terminal prescriptions are immutable")
        for item in items:
            item.validated()
        return replace(self, patient_id=patient_id, items=items, updated_at=now)

    def issue(self, *, now: datetime) -> Prescription:
        if self.status is not PrescriptionStatus.DRAFT:
            raise PrescriptionError("only draft prescriptions can be issued")
        if not self.items:
            raise PrescriptionError("a prescription requires at least one medication before issue")
        for item in self.items:
            item.validated()
        return replace(
            self,
            status=PrescriptionStatus.ISSUED,
            issued_at=now,
            updated_at=now,
        )

    def cancel(self, *, reason: str, now: datetime) -> Prescription:
        if self.status is not PrescriptionStatus.DRAFT:
            raise PrescriptionError("only draft prescriptions can be cancelled")
        if not reason.strip():
            raise PrescriptionError("cancel reason is required")
        return replace(
            self,
            status=PrescriptionStatus.CANCELLED,
            cancel_reason=reason.strip(),
            cancelled_at=now,
            updated_at=now,
        )

    def void(self, *, reason: str, now: datetime) -> Prescription:
        if self.status is not PrescriptionStatus.ISSUED:
            raise PrescriptionError("only issued prescriptions can be voided")
        if not reason.strip():
            raise PrescriptionError("void reason is required")
        return replace(
            self,
            status=PrescriptionStatus.VOIDED,
            void_reason=reason.strip(),
            voided_at=now,
            updated_at=now,
        )
