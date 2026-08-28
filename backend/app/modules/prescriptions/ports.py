"""Application ports for Electronic Prescription."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .domain import MedicationItem, Prescription, PrescriptionStatus


class PrescriptionRepository(Protocol):
    async def get(
        self, prescription_id: UUID, *, tenant_id: UUID, clinic_id: UUID, for_update: bool = False
    ) -> Prescription | None: ...

    async def list(
        self,
        *,
        tenant_id: UUID,
        clinic_id: UUID,
        patient_id: UUID | None = None,
        status: PrescriptionStatus | None = None,
    ) -> Sequence[Prescription]: ...

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
    ) -> Prescription: ...

    async def save(
        self,
        prescription: Prescription,
        *,
        actor_id: UUID,
        action: str,
        from_status: PrescriptionStatus | None,
        reason: str | None = None,
    ) -> Prescription: ...

    async def audit(
        self, prescription_id: UUID, *, tenant_id: UUID, clinic_id: UUID
    ) -> Sequence[dict]: ...


class PatientAccessPort(Protocol):
    async def exists_in_clinic(self, patient_id: UUID, *, clinic_id: UUID) -> bool: ...


class IdentifierGenerator(Protocol):
    def new(self, now: datetime) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
