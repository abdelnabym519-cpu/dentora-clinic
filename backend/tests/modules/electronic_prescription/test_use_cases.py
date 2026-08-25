from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.electronic_prescription.domain import MedicationItem, Prescription, PrescriptionError, PrescriptionStatus
from app.modules.electronic_prescription.use_cases import PrescriptionUseCases

NOW = datetime(2026, 8, 25, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class Identifiers:
    def new(self, now):
        return "RX-TEST-0001"


class Patients:
    def __init__(self, allowed: set[tuple[UUID, UUID]]):
        self.allowed = allowed

    async def exists_in_clinic(self, patient_id, *, clinic_id):
        return (patient_id, clinic_id) in self.allowed


class Repo:
    def __init__(self):
        self.rows: dict[UUID, Prescription] = {}
        self.events: list[dict] = []

    async def get(self, prescription_id, *, tenant_id, clinic_id, for_update=False):
        rx = self.rows.get(prescription_id)
        if rx and rx.tenant_id == tenant_id and rx.clinic_id == clinic_id:
            return rx
        return None

    async def list(self, *, tenant_id, clinic_id, patient_id=None, status=None):
        return [rx for rx in self.rows.values() if rx.tenant_id == tenant_id and rx.clinic_id == clinic_id and (patient_id is None or rx.patient_id == patient_id) and (status is None or rx.status is status)]

    async def create(self, *, tenant_id, clinic_id, patient_id, doctor_id, identifier, items, now):
        rx = Prescription(id=uuid4(), tenant_id=tenant_id, clinic_id=clinic_id, patient_id=patient_id, doctor_id=doctor_id, identifier=identifier, status=PrescriptionStatus.DRAFT, items=items, created_at=now, updated_at=now)
        self.rows[rx.id] = rx
        self.events.append({"action": "created", "prescription_id": rx.id})
        return rx

    async def save(self, prescription, *, actor_id, action, from_status, reason=None):
        self.rows[prescription.id] = prescription
        self.events.append({"action": action, "actor": actor_id, "from": from_status, "to": prescription.status, "reason": reason})
        return prescription

    async def audit(self, prescription_id, *, tenant_id, clinic_id):
        if await self.get(prescription_id, tenant_id=tenant_id, clinic_id=clinic_id):
            return [event for event in self.events if event.get("prescription_id", prescription_id) == prescription_id]
        return []


def med():
    return MedicationItem(medication_name="Ibuprofen", dose="400 mg", frequency="8 hourly", duration="3 days", route="oral", quantity=9)


@pytest.mark.asyncio
async def test_context_isolation_and_lifecycle_audit() -> None:
    tenant, clinic, patient, doctor = uuid4(), uuid4(), uuid4(), uuid4()
    repo = Repo()
    uc = PrescriptionUseCases(repo, Patients({(patient, clinic)}), clock=Clock(), identifiers=Identifiers())
    rx = await uc.create(tenant_id=tenant, clinic_id=clinic, patient_id=patient, doctor_id=doctor, items=(med(),))
    assert rx.identifier == "RX-TEST-0001"
    assert await uc.list(tenant_id=tenant, clinic_id=clinic) == [rx]
    assert await uc.list(tenant_id=uuid4(), clinic_id=clinic) == []
    with pytest.raises(PrescriptionError, match="not found"):
        await uc.get(rx.id, tenant_id=tenant, clinic_id=uuid4())
    issued = await uc.issue(rx.id, tenant_id=tenant, clinic_id=clinic, actor_id=doctor)
    assert issued.status is PrescriptionStatus.ISSUED
    voided = await uc.void(rx.id, tenant_id=tenant, clinic_id=clinic, actor_id=doctor, reason="entered in error")
    assert voided.status is PrescriptionStatus.VOIDED
    assert [e["action"] for e in repo.events] == ["created", "issued", "voided"]


@pytest.mark.asyncio
async def test_cross_clinic_patient_and_non_owner_are_rejected() -> None:
    tenant, clinic, patient, doctor = uuid4(), uuid4(), uuid4(), uuid4()
    repo = Repo()
    uc = PrescriptionUseCases(repo, Patients({(patient, clinic)}), clock=Clock(), identifiers=Identifiers())
    with pytest.raises(PrescriptionError, match="selected clinic"):
        await uc.create(tenant_id=tenant, clinic_id=uuid4(), patient_id=patient, doctor_id=doctor, items=(med(),))
    rx = await uc.create(tenant_id=tenant, clinic_id=clinic, patient_id=patient, doctor_id=doctor, items=(med(),))
    with pytest.raises(PrescriptionError, match="prescribing doctor"):
        await uc.issue(rx.id, tenant_id=tenant, clinic_id=clinic, actor_id=uuid4())
