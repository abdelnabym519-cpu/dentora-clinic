"""Electronic Prescription application use cases."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from .domain import MedicationItem, Prescription, PrescriptionError, PrescriptionStatus
from .ports import Clock, IdentifierGenerator, PatientAccessPort, PrescriptionRepository


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SecurePrescriptionIdentifier:
    def new(self, now: datetime) -> str:
        return f"RX-{now:%Y%m%d}-{uuid4().hex[:12].upper()}"


class PrescriptionUseCases:
    """Business orchestration with no dependency on FastAPI or SQLAlchemy."""

    def __init__(
        self,
        repository: PrescriptionRepository,
        patient_access: PatientAccessPort,
        *,
        clock: Clock | None = None,
        identifiers: IdentifierGenerator | None = None,
    ) -> None:
        self.repository = repository
        self.patient_access = patient_access
        self.clock = clock or SystemClock()
        self.identifiers = identifiers or SecurePrescriptionIdentifier()

    async def _assert_patient(self, patient_id: UUID, clinic_id: UUID) -> None:
        if not await self.patient_access.exists_in_clinic(patient_id, clinic_id=clinic_id):
            raise PrescriptionError("patient is not available in the selected clinic")

    async def _owned_for_update(
        self, prescription_id: UUID, *, tenant_id: UUID, clinic_id: UUID, actor_id: UUID
    ) -> Prescription:
        rx = await self.repository.get(
            prescription_id, tenant_id=tenant_id, clinic_id=clinic_id, for_update=True
        )
        if rx is None:
            raise PrescriptionError("prescription not found")
        rx.assert_owned_by(actor_id)
        return rx

    async def create(
        self,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        patient_id: UUID,
        doctor_id: UUID,
        items: tuple[MedicationItem, ...],
    ) -> Prescription:
        await self._assert_patient(patient_id, clinic_id)
        for item in items:
            item.validated()
        now = self.clock.now()
        return await self.repository.create(
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            identifier=self.identifiers.new(now),
            items=items,
            now=now,
        )

    async def update(
        self,
        prescription_id: UUID,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        actor_id: UUID,
        patient_id: UUID,
        items: tuple[MedicationItem, ...],
    ) -> Prescription:
        rx = await self._owned_for_update(
            prescription_id, tenant_id=tenant_id, clinic_id=clinic_id, actor_id=actor_id
        )
        await self._assert_patient(patient_id, clinic_id)
        updated = rx.update_draft(patient_id=patient_id, items=items, now=self.clock.now())
        return await self.repository.save(
            updated, actor_id=actor_id, action="updated", from_status=rx.status
        )

    async def issue(
        self, prescription_id: UUID, *, tenant_id: UUID, clinic_id: UUID, actor_id: UUID
    ) -> Prescription:
        rx = await self._owned_for_update(
            prescription_id, tenant_id=tenant_id, clinic_id=clinic_id, actor_id=actor_id
        )
        issued = rx.issue(now=self.clock.now())
        return await self.repository.save(
            issued, actor_id=actor_id, action="issued", from_status=rx.status
        )

    async def cancel(
        self,
        prescription_id: UUID,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> Prescription:
        rx = await self._owned_for_update(
            prescription_id, tenant_id=tenant_id, clinic_id=clinic_id, actor_id=actor_id
        )
        cancelled = rx.cancel(reason=reason, now=self.clock.now())
        return await self.repository.save(
            cancelled,
            actor_id=actor_id,
            action="cancelled",
            from_status=rx.status,
            reason=reason.strip(),
        )

    async def void(
        self,
        prescription_id: UUID,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> Prescription:
        rx = await self._owned_for_update(
            prescription_id, tenant_id=tenant_id, clinic_id=clinic_id, actor_id=actor_id
        )
        voided = rx.void(reason=reason, now=self.clock.now())
        return await self.repository.save(
            voided,
            actor_id=actor_id,
            action="voided",
            from_status=rx.status,
            reason=reason.strip(),
        )

    async def get(self, prescription_id: UUID, *, tenant_id: UUID, clinic_id: UUID) -> Prescription:
        rx = await self.repository.get(prescription_id, tenant_id=tenant_id, clinic_id=clinic_id)
        if rx is None:
            raise PrescriptionError("prescription not found")
        return rx

    async def list(
        self,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        patient_id: UUID | None = None,
        status: PrescriptionStatus | None = None,
    ) -> Sequence[Prescription]:
        return await self.repository.list(
            tenant_id=tenant_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            status=status,
        )

    async def audit(
        self, prescription_id: UUID, *, tenant_id: UUID, clinic_id: UUID
    ) -> Sequence[dict]:
        await self.get(prescription_id, tenant_id=tenant_id, clinic_id=clinic_id)
        return await self.repository.audit(
            prescription_id, tenant_id=tenant_id, clinic_id=clinic_id
        )
