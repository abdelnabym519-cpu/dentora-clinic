"""SQLAlchemy adapters implementing Electronic Prescription ports."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.patients.models import Patient

from .domain import MedicationItem, Prescription, PrescriptionStatus
from .models import PrescriptionAuditRecord, PrescriptionItemRecord, PrescriptionRecord


def _to_domain(row: PrescriptionRecord) -> Prescription:
    return Prescription(
        id=row.id,
        tenant_id=row.tenant_id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        doctor_id=row.doctor_id,
        identifier=row.identifier,
        status=PrescriptionStatus(row.status),
        items=tuple(
            MedicationItem(
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
            for item in row.items
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        issued_at=row.issued_at,
        cancelled_at=row.cancelled_at,
        voided_at=row.voided_at,
        cancel_reason=row.cancel_reason,
        void_reason=row.void_reason,
    )


class SqlAlchemyPatientAccess:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists_in_clinic(self, patient_id: UUID, *, clinic_id: UUID) -> bool:
        result = await self.session.execute(
            select(Patient.id).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
        )
        return result.scalar_one_or_none() is not None


class SqlAlchemyPrescriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _row(
        self,
        prescription_id: UUID,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        for_update: bool = False,
    ) -> PrescriptionRecord | None:
        query = (
            select(PrescriptionRecord)
            .options(selectinload(PrescriptionRecord.items))
            .where(
                PrescriptionRecord.id == prescription_id,
                PrescriptionRecord.tenant_id == tenant_id,
                PrescriptionRecord.clinic_id == clinic_id,
            )
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get(
        self,
        prescription_id: UUID,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        for_update: bool = False,
    ) -> Prescription | None:
        row = await self._row(
            prescription_id, tenant_id=tenant_id, clinic_id=clinic_id, for_update=for_update
        )
        return _to_domain(row) if row is not None else None

    async def list(
        self,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        patient_id: UUID | None = None,
        status: PrescriptionStatus | None = None,
    ) -> Sequence[Prescription]:
        query = (
            select(PrescriptionRecord)
            .options(selectinload(PrescriptionRecord.items))
            .where(
                PrescriptionRecord.tenant_id == tenant_id,
                PrescriptionRecord.clinic_id == clinic_id,
            )
            .order_by(PrescriptionRecord.created_at.desc())
        )
        if patient_id is not None:
            query = query.where(PrescriptionRecord.patient_id == patient_id)
        if status is not None:
            query = query.where(PrescriptionRecord.status == status.value)
        result = await self.session.execute(query)
        return [_to_domain(row) for row in result.scalars().unique().all()]

    @staticmethod
    def _item_rows(items: tuple[MedicationItem, ...]) -> list[PrescriptionItemRecord]:
        return [
            PrescriptionItemRecord(
                position=position,
                medication_name=item.medication_name.strip(),
                strength=item.strength.strip() if item.strength else None,
                dose=item.dose.strip(),
                frequency=item.frequency.strip(),
                duration=item.duration.strip(),
                route=item.route.strip(),
                instructions=item.instructions.strip() if item.instructions else None,
                quantity=item.quantity,
                quantity_unit=item.quantity_unit.strip() if item.quantity_unit else None,
            )
            for position, item in enumerate(items)
        ]

    async def create(
        self,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        patient_id: UUID,
        doctor_id: UUID,
        identifier: str,
        items: tuple[MedicationItem, ...],
        now: datetime,
    ) -> Prescription:
        row = PrescriptionRecord(
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            identifier=identifier,
            status=PrescriptionStatus.DRAFT.value,
            created_at=now,
            updated_at=now,
            items=self._item_rows(items),
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add(
            PrescriptionAuditRecord(
                tenant_id=tenant_id,
                clinic_id=clinic_id,
                prescription_id=row.id,
                actor_user_id=doctor_id,
                action="created",
                from_status=None,
                to_status=PrescriptionStatus.DRAFT.value,
                reason=None,
                details={"item_count": len(items)},
                created_at=now,
            )
        )
        await self.session.flush()
        return _to_domain(row)

    async def save(
        self,
        prescription: Prescription,
        *,
        actor_id: UUID,
        action: str,
        from_status: PrescriptionStatus | None,
        reason: str | None = None,
    ) -> Prescription:
        row = await self._row(
            prescription.id,
            tenant_id=prescription.tenant_id,
            clinic_id=prescription.clinic_id,
            for_update=True,
        )
        if row is None:
            raise LookupError("prescription disappeared during update")
        row.patient_id = prescription.patient_id
        row.status = prescription.status.value
        row.issued_at = prescription.issued_at
        row.cancelled_at = prescription.cancelled_at
        row.voided_at = prescription.voided_at
        row.cancel_reason = prescription.cancel_reason
        row.void_reason = prescription.void_reason
        row.updated_at = prescription.updated_at
        if action == "updated":
            await self.session.execute(
                delete(PrescriptionItemRecord).where(
                    PrescriptionItemRecord.prescription_id == prescription.id
                )
            )
            row.items = self._item_rows(prescription.items)
        self.session.add(
            PrescriptionAuditRecord(
                tenant_id=prescription.tenant_id,
                clinic_id=prescription.clinic_id,
                prescription_id=prescription.id,
                actor_user_id=actor_id,
                action=action,
                from_status=from_status.value if from_status else None,
                to_status=prescription.status.value,
                reason=reason,
                details={"item_count": len(prescription.items)},
                created_at=prescription.updated_at,
            )
        )
        await self.session.flush()
        refreshed = await self._row(
            prescription.id,
            tenant_id=prescription.tenant_id,
            clinic_id=prescription.clinic_id,
        )
        assert refreshed is not None
        return _to_domain(refreshed)

    async def audit(
        self, prescription_id: UUID, *, tenant_id: UUID, clinic_id: UUID
    ) -> Sequence[dict]:
        result = await self.session.execute(
            select(PrescriptionAuditRecord)
            .where(
                PrescriptionAuditRecord.prescription_id == prescription_id,
                PrescriptionAuditRecord.tenant_id == tenant_id,
                PrescriptionAuditRecord.clinic_id == clinic_id,
            )
            .order_by(PrescriptionAuditRecord.created_at.asc())
        )
        return [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "action": row.action,
                "from_status": row.from_status,
                "to_status": row.to_status,
                "reason": row.reason,
                "details": row.details,
                "created_at": row.created_at,
            }
            for row in result.scalars().all()
        ]
