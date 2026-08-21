"""Patient application service.

Business workflows depend only on the patient ports and pure domain model.
Database, ORM, HTTP, and event-bus implementations are injected by the
outer composition layer.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from .domain import PatientEntity
from .ports import (
    PatientEventPublisher,
    PatientListSpec,
    PatientRepository,
    PatientSort,
    PatientSortDirection,
)

_SORT_FIELDS = frozenset({"last_name", "first_name", "created_at", "updated_at"})
_SORT_DEFAULT = "last_visit:desc"
_SORT_LAST_VISIT = "last_visit"
_SORT_DIRECTIONS = frozenset({"asc", "desc"})


class InvalidPatientSortError(ValueError):
    """Raised when a patient list sort expression is invalid."""


def _parse_sort(value: str | None) -> PatientSort:
    raw = (value or _SORT_DEFAULT).strip()
    if not raw:
        raise InvalidPatientSortError("Empty sort value")

    field, _, direction = raw.partition(":")
    field = field.strip()
    direction = (direction or "asc").strip().lower()

    if field != _SORT_LAST_VISIT and field not in _SORT_FIELDS:
        raise InvalidPatientSortError(
            f"Invalid sort field {field!r}. Allowed: {sorted(_SORT_FIELDS)}"
        )
    if direction not in _SORT_DIRECTIONS:
        raise InvalidPatientSortError(
            f"Invalid sort direction {direction!r}. Use 'asc' or 'desc'."
        )

    return PatientSort(
        field=field,
        direction=cast(PatientSortDirection, direction),
    )


class PatientService:
    """Patient use cases with explicit, replaceable dependencies."""

    def __init__(
        self,
        repository: PatientRepository,
        events: PatientEventPublisher,
    ) -> None:
        self._repository = repository
        self._events = events

    async def get_recent_patients(
        self,
        clinic_id: UUID,
        limit: int = 8,
    ) -> list[PatientEntity]:
        """Return recent active patients."""
        return await self._repository.get_recent(clinic_id, limit)

    async def list_patients(
        self,
        clinic_id: UUID,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
        *,
        patient_ids: list[UUID] | None = None,
        city: str | None = None,
        do_not_contact: bool | None = None,
        include_archived: bool = False,
        sort: str | None = None,
    ) -> tuple[list[PatientEntity], int]:
        """List patients using persistence-neutral filter criteria."""
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)

        if patient_ids is not None and not patient_ids:
            return [], 0

        spec = PatientListSpec(
            search=search,
            page=page,
            page_size=page_size,
            patient_ids=tuple(patient_ids) if patient_ids is not None else None,
            city=city,
            do_not_contact=do_not_contact,
            include_archived=include_archived,
            sort=_parse_sort(sort),
        )
        return await self._repository.list(clinic_id, spec)

    async def get_patient(
        self,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> PatientEntity | None:
        """Get one clinic-scoped patient."""
        return await self._repository.get(clinic_id, patient_id)

    async def create_patient(self, clinic_id: UUID, data: dict) -> PatientEntity:
        """Create a patient and publish the existing lifecycle event."""
        patient = await self._repository.create(clinic_id, data)
        await self._events.patient_created(patient)
        return patient

    async def update_patient(
        self,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
    ) -> PatientEntity | None:
        """Update a patient and publish an event only when it exists."""
        patient = await self._repository.update(clinic_id, patient_id, data)
        if patient is None:
            return None

        await self._events.patient_updated(patient, tuple(data.keys()))
        return patient

    async def archive_patient(
        self,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> PatientEntity | None:
        """Soft-delete a patient and publish the existing lifecycle event."""
        patient = await self._repository.archive(clinic_id, patient_id)
        if patient is None:
            return None

        await self._events.patient_archived(patient)
        return patient
