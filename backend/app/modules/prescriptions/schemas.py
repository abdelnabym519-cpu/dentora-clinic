"""Pydantic contracts for Electronic Prescription API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .domain import Prescription, PrescriptionStatus


class MedicationItemInput(BaseModel):
    medication_name: str = Field(min_length=1, max_length=200)
    strength: str | None = Field(default=None, max_length=100)
    dose: str = Field(min_length=1, max_length=100)
    frequency: str = Field(min_length=1, max_length=100)
    duration: str = Field(min_length=1, max_length=100)
    route: str = Field(min_length=1, max_length=100)
    instructions: str | None = Field(default=None, max_length=2000)
    quantity: int = Field(gt=0, le=100000)
    quantity_unit: str | None = Field(default=None, max_length=50)


class PrescriptionCreate(BaseModel):
    patient_id: UUID
    items: list[MedicationItemInput] = Field(default_factory=list, max_length=50)


class PrescriptionUpdate(PrescriptionCreate):
    pass


class TransitionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class MedicationItemResponse(MedicationItemInput):
    id: UUID | None = None


class PrescriptionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    clinic_id: UUID
    patient_id: UUID
    doctor_id: UUID
    identifier: str
    status: PrescriptionStatus
    items: list[MedicationItemResponse]
    created_at: datetime
    updated_at: datetime
    issued_at: datetime | None
    cancelled_at: datetime | None
    voided_at: datetime | None
    cancel_reason: str | None
    void_reason: str | None

    @classmethod
    def from_domain(cls, rx: Prescription) -> "PrescriptionResponse":
        return cls(
            id=rx.id,
            tenant_id=rx.tenant_id,
            clinic_id=rx.clinic_id,
            patient_id=rx.patient_id,
            doctor_id=rx.doctor_id,
            identifier=rx.identifier,
            status=rx.status,
            items=[
                MedicationItemResponse(
                    id=item.id,
                    medication_name=item.medication_name,
                    strength=item.strength,
                    dose=item.dose,
                    frequency=item.frequency,
                    duration=item.duration,
                    route=item.route,
                    instructions=item.instructions,
                    quantity=item.quantity,
                    quantity_unit=item.quantity_unit,
                )
                for item in rx.items
            ],
            created_at=rx.created_at,
            updated_at=rx.updated_at,
            issued_at=rx.issued_at,
            cancelled_at=rx.cancelled_at,
            voided_at=rx.voided_at,
            cancel_reason=rx.cancel_reason,
            void_reason=rx.void_reason,
        )


class AuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID
    action: str
    from_status: str | None
    to_status: str
    reason: str | None
    details: dict
    created_at: datetime
