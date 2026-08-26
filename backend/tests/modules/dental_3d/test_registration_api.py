"""HTTP contract tests for patient-specific registration."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.modules.patients.models import Patient


def _url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/alignment"


def _payload() -> dict[str, str]:
    return {
        "mesh_document_id": str(uuid4()),
        "series_instance_uid": "1.2.3.4",
        "ios_units": "mm",
    }


@pytest.mark.asyncio
async def test_run_persists_safe_missing_input_and_get_returns_it(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    assert (await client.get(_url(test_patient.id), headers=auth_headers)).status_code == 404
    created = await client.post(_url(test_patient.id), headers=auth_headers, json=_payload())
    assert created.status_code == 201
    body = created.json()["data"]
    assert body["status"] == "failed"
    assert body["failure"]["code"] == "missing_cbct"
    assert body["transform"] is None
    assert body["requires_review"] is False
    latest = await client.get(_url(test_patient.id), headers=auth_headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["id"] == body["id"]


@pytest.mark.asyncio
async def test_units_are_required_and_unknown_units_rejected(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    missing = _payload()
    missing.pop("ios_units")
    assert (
        await client.post(_url(test_patient.id), headers=auth_headers, json=missing)
    ).status_code == 422
    unknown = _payload()
    unknown["ios_units"] = "scanner_native"
    assert (
        await client.post(_url(test_patient.id), headers=auth_headers, json=unknown)
    ).status_code == 422


@pytest.mark.asyncio
async def test_failed_alignment_cannot_be_reviewed(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    body = (await client.post(_url(test_patient.id), headers=auth_headers, json=_payload())).json()[
        "data"
    ]
    response = await client.post(
        f"{_url(test_patient.id)}/{body['id']}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_authentication_is_required(client: AsyncClient, test_patient: Patient) -> None:
    assert (await client.post(_url(test_patient.id), json=_payload())).status_code == 401
    assert (await client.get(_url(test_patient.id))).status_code == 401
