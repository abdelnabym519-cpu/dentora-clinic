"""Pure unit tests for patient use cases."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.patients.domain import PatientEntity
from app.modules.patients.ports import PatientListSpec
from app.modules.patients.service import InvalidPatientSortError, PatientService


def make_patient(
    *,
    clinic_id: UUID | None = None,
    patient_id: UUID | None = None,
    status: str = "active",
) -> PatientEntity:
    now = datetime.now(UTC)
    return PatientEntity(
        id=patient_id or uuid4(),
        clinic_id=clinic_id or uuid4(),
        first_name="Ana",
        last_name="Martin",
        phone="+34123456789",
        email="ana@example.test",
        date_of_birth=None,
        notes=None,
        status=status,
        do_not_contact=False,
        gender=None,
        national_id=None,
        national_id_type=None,
        profession=None,
        workplace=None,
        preferred_language="es",
        address=None,
        photo_url=None,
        billing_name=None,
        billing_tax_id=None,
        billing_address=None,
        billing_email=None,
        created_at=now,
        updated_at=now,
    )


class FakePatientRepository:
    def __init__(self, patient: PatientEntity) -> None:
        self.patient = patient
        self.list_spec: PatientListSpec | None = None
        self.list_calls = 0
        self.missing = False

    async def get_recent(self, clinic_id: UUID, limit: int) -> list[PatientEntity]:
        return [self.patient]

    async def list(
        self,
        clinic_id: UUID,
        spec: PatientListSpec,
    ) -> tuple[list[PatientEntity], int]:
        self.list_calls += 1
        self.list_spec = spec
        return [self.patient], 1

    async def get(self, clinic_id: UUID, patient_id: UUID) -> PatientEntity | None:
        return None if self.missing else self.patient

    async def create(self, clinic_id: UUID, data: dict) -> PatientEntity:
        return self.patient

    async def update(
        self,
        clinic_id: UUID,
        patient_id: UUID,
        data: dict,
    ) -> PatientEntity | None:
        return None if self.missing else self.patient

    async def archive(
        self,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> PatientEntity | None:
        return None if self.missing else self.patient


class RecordingPatientEvents:
    def __init__(self) -> None:
        self.created: list[PatientEntity] = []
        self.updated: list[tuple[PatientEntity, tuple[str, ...]]] = []
        self.archived: list[PatientEntity] = []

    async def patient_created(self, patient: PatientEntity) -> None:
        self.created.append(patient)

    async def patient_updated(
        self,
        patient: PatientEntity,
        changed_fields: tuple[str, ...],
    ) -> None:
        self.updated.append((patient, changed_fields))

    async def patient_archived(self, patient: PatientEntity) -> None:
        self.archived.append(patient)


def build_service() -> tuple[PatientService, FakePatientRepository, RecordingPatientEvents]:
    patient = make_patient()
    repository = FakePatientRepository(patient)
    events = RecordingPatientEvents()
    return PatientService(repository, events), repository, events


@pytest.mark.asyncio
async def test_list_patients_normalizes_pagination_and_sort_without_database() -> None:
    service, repository, _ = build_service()

    patients, total = await service.list_patients(
        repository.patient.clinic_id,
        page=0,
        page_size=500,
    )

    assert patients == [repository.patient]
    assert total == 1
    assert repository.list_spec is not None
    assert repository.list_spec.page == 1
    assert repository.list_spec.page_size == 100
    assert repository.list_spec.sort.field == "last_visit"
    assert repository.list_spec.sort.direction == "desc"


@pytest.mark.asyncio
async def test_list_patients_empty_intersection_short_circuits_repository() -> None:
    service, repository, _ = build_service()

    result = await service.list_patients(
        repository.patient.clinic_id,
        patient_ids=[],
    )

    assert result == ([], 0)
    assert repository.list_calls == 0


@pytest.mark.asyncio
async def test_list_patients_rejects_unknown_sort_before_repository_call() -> None:
    service, repository, _ = build_service()

    with pytest.raises(InvalidPatientSortError, match="Invalid sort field"):
        await service.list_patients(
            repository.patient.clinic_id,
            sort="secret_column:desc",
        )

    assert repository.list_calls == 0


@pytest.mark.asyncio
async def test_list_patients_rejects_invalid_sort_direction() -> None:
    service, repository, _ = build_service()

    with pytest.raises(InvalidPatientSortError, match="Invalid sort direction"):
        await service.list_patients(
            repository.patient.clinic_id,
            sort="last_visit:sideways",
        )

    assert repository.list_calls == 0


@pytest.mark.asyncio
async def test_create_patient_publishes_event_after_repository_success() -> None:
    service, repository, events = build_service()

    patient = await service.create_patient(
        repository.patient.clinic_id,
        {"first_name": "Ana", "last_name": "Martin"},
    )

    assert patient == repository.patient
    assert events.created == [repository.patient]


@pytest.mark.asyncio
async def test_update_patient_publishes_changed_fields() -> None:
    service, repository, events = build_service()

    patient = await service.update_patient(
        repository.patient.clinic_id,
        repository.patient.id,
        {"phone": "+34999999999", "notes": None},
    )

    assert patient == repository.patient
    assert events.updated == [(repository.patient, ("phone", "notes"))]


@pytest.mark.asyncio
async def test_missing_update_does_not_publish_event() -> None:
    service, repository, events = build_service()
    repository.missing = True

    patient = await service.update_patient(
        repository.patient.clinic_id,
        repository.patient.id,
        {"phone": "+34999999999"},
    )

    assert patient is None
    assert events.updated == []


@pytest.mark.asyncio
async def test_archive_patient_publishes_event() -> None:
    service, repository, events = build_service()

    patient = await service.archive_patient(
        repository.patient.clinic_id,
        repository.patient.id,
    )

    assert patient == repository.patient
    assert events.archived == [repository.patient]
