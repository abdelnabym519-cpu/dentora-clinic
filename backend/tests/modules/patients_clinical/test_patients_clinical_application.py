"""DB-free tests for the patients_clinical application boundary."""

from typing import Any

import pytest

from app.modules.patients_clinical.application import PatientsClinicalApplication


class FakePatientsClinicalGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def invoke(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((operation, args, kwargs))
        return {"operation": operation}


@pytest.mark.asyncio
async def test_patients_clinical_application_delegates_to_injected_gateway() -> None:
    gateway = FakePatientsClinicalGateway()
    app = PatientsClinicalApplication(gateway)

    result = await app.invoke("get_medical_context", "db", "patient")

    assert result == {"operation": "get_medical_context"}
    assert gateway.calls == [("get_medical_context", ("db", "patient"), {})]


@pytest.mark.asyncio
async def test_patients_clinical_application_preserves_keyword_arguments() -> None:
    gateway = FakePatientsClinicalGateway()
    app = PatientsClinicalApplication(gateway)

    await app.invoke("upsert_medical_context", "db", "clinic", "patient", {}, user_id="user")

    assert gateway.calls[0][2] == {"user_id": "user"}
