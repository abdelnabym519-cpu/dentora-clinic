"""Application ports for the patients module.

Ports describe what patient use cases need. Concrete database and event-bus
implementations live outside the application service and depend on these
contracts, not the other way around.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from .domain import PatientEntity

PatientSortDirection = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class PatientSort:
    """Validated sort request independent from SQL/ORM expressions."""

    field: str
    direction: PatientSortDirection


@dataclass(frozen=True, slots=True)
class PatientListSpec:
    """Persistence-neutral criteria for listing patients."""

    search: str | None
    page: int
    page_size: int
    patient_ids: tuple[UUID, ...] | None
    city: str | None
    do_not_contact: bool | None
    include_archived: bool
    sort: PatientSort


class PatientRepository(Protocol):
    """Persistence operations required by patient use cases."""

    async def get_recent(self, clinic_id: UUID, limit: int) -> list[PatientEntity]:
        """Return recent active patients in product-defined order."""
        ...

    async def list(
        self,
        clinic_id: UUID,
        spec: PatientListSpec,
    ) -> tuple[list[PatientEntity], int]:
        """Return a page plus the total matching count."""
        ...

    async def get(self, clinic_id: UUID, patient_id: UUID) -> PatientEntity | None:
        """Return one patient scoped to a clinic."""
        ...

    async def create(self, clinic_id: UUID, data: dict) -> PatientEntity:
        """Persist a new patient and return its domain representation."""
        ...

    async def update(
        self,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
    ) -> PatientEntity | None:
        """Update one clinic-scoped patient, or return ``None`` if absent."""
        ...

    async def archive(
        self,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> PatientEntity | None:
        """Soft-delete one patient, or return ``None`` if absent."""
        ...


class PatientEventPublisher(Protocol):
    """Application-facing event port for patient lifecycle events."""

    async def patient_created(self, patient: PatientEntity) -> None:
        """Publish a patient-created event."""
        ...

    async def patient_updated(
        self,
        patient: PatientEntity,
        changed_fields: tuple[str, ...],
    ) -> None:
        """Publish a patient-updated event."""
        ...

    async def patient_archived(self, patient: PatientEntity) -> None:
        """Publish a patient-archived event."""
        ...
