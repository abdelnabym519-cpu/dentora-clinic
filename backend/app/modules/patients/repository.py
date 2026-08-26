"""SQLAlchemy persistence adapter for patient application ports."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import and_, column, func, or_, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from .domain import PatientEntity
from .models import Patient
from .ports import PatientListSpec, PatientRepository, PatientSortDirection

_SORT_COLUMNS = {
    "last_name": Patient.last_name,
    "first_name": Patient.first_name,
    "created_at": Patient.created_at,
    "updated_at": Patient.updated_at,
}

# ``patients`` is foundational and must not import the agenda model. A
# lightweight SQLAlchemy table contract keeps that module boundary intact.
_appointments = table(
    "appointments",
    column("patient_id"),
    column("clinic_id"),
    column("start_time"),
)

_SEARCH_FIELDS = (
    Patient.first_name,
    Patient.last_name,
    Patient.phone,
    Patient.email,
    Patient.national_id,
)
_FULL_NAME = func.concat(Patient.first_name, " ", Patient.last_name)


def _search_condition(search: str | None):
    if not search or not search.strip():
        return None

    per_term = []
    for term in search.split():
        like = f"%{term}%"
        per_term.append(
            or_(
                *(field.ilike(like) for field in _SEARCH_FIELDS),
                _FULL_NAME.ilike(like),
            )
        )
    return and_(*per_term)


def _to_entity(patient: Patient) -> PatientEntity:
    """Map the infrastructure ORM model to a persistence-neutral entity."""
    return PatientEntity(
        id=patient.id,
        clinic_id=patient.clinic_id,
        first_name=patient.first_name,
        last_name=patient.last_name,
        phone=patient.phone,
        email=patient.email,
        date_of_birth=patient.date_of_birth,
        notes=patient.notes,
        status=patient.status,
        do_not_contact=patient.do_not_contact,
        gender=patient.gender,
        national_id=patient.national_id,
        national_id_type=patient.national_id_type,
        profession=patient.profession,
        workplace=patient.workplace,
        preferred_language=patient.preferred_language,
        address=patient.address,
        photo_url=patient.photo_url,
        billing_name=patient.billing_name,
        billing_tax_id=patient.billing_tax_id,
        billing_address=patient.billing_address,
        billing_email=patient.billing_email,
        created_at=patient.created_at,
        updated_at=patient.updated_at,
    )


class SqlAlchemyPatientRepository(PatientRepository):
    """PostgreSQL/SQLAlchemy implementation of :class:`PatientRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recent(self, clinic_id: UUID, limit: int) -> list[PatientEntity]:
        last_visit_rows = (
            await self._session.execute(
                select(
                    _appointments.c.patient_id,
                    func.max(_appointments.c.start_time).label("last_visit"),
                )
                .where(
                    _appointments.c.clinic_id == clinic_id,
                    _appointments.c.patient_id.is_not(None),
                )
                .group_by(_appointments.c.patient_id)
                .order_by(func.max(_appointments.c.start_time).desc())
                .limit(limit)
            )
        ).all()

        ordered_ids = [row.patient_id for row in last_visit_rows]

        if not ordered_ids:
            result = await self._session.execute(
                select(Patient)
                .where(
                    Patient.clinic_id == clinic_id,
                    Patient.status != "archived",
                )
                .order_by(Patient.created_at.desc())
                .limit(limit)
            )
            return [_to_entity(patient) for patient in result.scalars().all()]

        result = await self._session.execute(
            select(Patient).where(
                Patient.clinic_id == clinic_id,
                Patient.id.in_(ordered_ids),
                Patient.status != "archived",
            )
        )
        by_id = {patient.id: patient for patient in result.scalars().all()}
        return [_to_entity(by_id[patient_id]) for patient_id in ordered_ids if patient_id in by_id]

    async def list(
        self,
        clinic_id: UUID,
        spec: PatientListSpec,
    ) -> tuple[list[PatientEntity], int]:
        conditions = [Patient.clinic_id == clinic_id]

        if not spec.include_archived:
            conditions.append(Patient.status != "archived")
        if spec.patient_ids:
            conditions.append(Patient.id.in_(spec.patient_ids))
        if spec.city:
            conditions.append(Patient.address["city"].astext.ilike(f"%{spec.city}%"))
        if spec.do_not_contact is not None:
            conditions.append(Patient.do_not_contact.is_(spec.do_not_contact))

        search_clause = _search_condition(spec.search)
        if search_clause is not None:
            conditions.append(search_clause)

        total = (
            await self._session.execute(select(func.count(Patient.id)).where(*conditions))
        ).scalar() or 0

        offset = (spec.page - 1) * spec.page_size

        if spec.sort.field == "last_visit":
            last_visit = (
                select(
                    _appointments.c.patient_id.label("patient_id"),
                    func.max(_appointments.c.start_time).label("last_visit"),
                )
                .where(
                    _appointments.c.clinic_id == clinic_id,
                    _appointments.c.patient_id.is_not(None),
                )
                .group_by(_appointments.c.patient_id)
                .subquery()
            )
            last_visit_col = last_visit.c.last_visit
            order_clause = (
                last_visit_col.desc().nulls_last()
                if spec.sort.direction == "desc"
                else last_visit_col.asc().nulls_last()
            )
            query = (
                select(Patient)
                .outerjoin(last_visit, last_visit.c.patient_id == Patient.id)
                .where(*conditions)
                .order_by(order_clause, Patient.last_name, Patient.first_name)
                .offset(offset)
                .limit(spec.page_size)
            )
        else:
            direction = cast(PatientSortDirection, spec.sort.direction)
            sort_column = _SORT_COLUMNS[spec.sort.field]
            order_clause = sort_column.asc() if direction == "asc" else sort_column.desc()
            query = (
                select(Patient)
                .where(*conditions)
                .order_by(order_clause, Patient.first_name)
                .offset(offset)
                .limit(spec.page_size)
            )

        result = await self._session.execute(query)
        return [_to_entity(patient) for patient in result.scalars().all()], int(total)

    async def get(self, clinic_id: UUID, patient_id: UUID) -> PatientEntity | None:
        patient = await self._get_model(clinic_id, patient_id)
        return _to_entity(patient) if patient is not None else None

    async def create(self, clinic_id: UUID, data: dict) -> PatientEntity:
        patient = Patient(clinic_id=clinic_id, **data)
        self._session.add(patient)
        await self._session.flush()
        return _to_entity(patient)

    async def update(
        self,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
    ) -> PatientEntity | None:
        patient = await self._get_model(clinic_id, patient_id)
        if patient is None:
            return None

        for key, value in data.items():
            setattr(patient, key, value)

        await self._session.flush()
        return _to_entity(patient)

    async def archive(
        self,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> PatientEntity | None:
        patient = await self._get_model(clinic_id, patient_id)
        if patient is None:
            return None

        patient.status = "archived"
        await self._session.flush()
        return _to_entity(patient)

    async def _get_model(self, clinic_id: UUID, patient_id: UUID) -> Patient | None:
        result = await self._session.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.clinic_id == clinic_id,
            )
        )
        return result.scalar_one_or_none()
