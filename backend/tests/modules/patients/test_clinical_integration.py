"""Regression coverage for Patients consumers outside the migrated module."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.patients.service import PatientService
from app.modules.patients_clinical.router import _ensure_patient


@pytest.mark.asyncio
async def test_clinical_patient_guard_uses_injected_patient_service(monkeypatch) -> None:
    """Clinical routes must call the instance-based Patients application service."""
    db = MagicMock(spec=AsyncSession)
    clinic_id = uuid4()
    patient_id = uuid4()
    seen: dict[str, object] = {}

    async def fake_get_patient(self: PatientService, actual_clinic_id, actual_patient_id) -> object:
        seen["service"] = self
        seen["clinic_id"] = actual_clinic_id
        seen["patient_id"] = actual_patient_id
        return object()

    monkeypatch.setattr(PatientService, "get_patient", fake_get_patient)

    await _ensure_patient(db, clinic_id, patient_id)

    assert isinstance(seen["service"], PatientService)
    assert seen["clinic_id"] == clinic_id
    assert seen["patient_id"] == patient_id


@pytest.mark.asyncio
async def test_clinical_patient_guard_preserves_not_found_contract(monkeypatch) -> None:
    """The integration adapter must keep the existing 404 behavior for missing patients."""
    db = MagicMock(spec=AsyncSession)

    async def fake_get_patient(self: PatientService, actual_clinic_id, actual_patient_id):
        return None

    monkeypatch.setattr(PatientService, "get_patient", fake_get_patient)

    with pytest.raises(HTTPException) as exc_info:
        await _ensure_patient(db, uuid4(), uuid4())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Patient not found"
