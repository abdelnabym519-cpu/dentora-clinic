"""API tests for the Phase 3 segmentation endpoints.

Exercises the mounted router at ``/api/v1/dental_3d/`` through the
ASGI client: run → latest → review workflow, RBAC boundaries
(write-only actions), clinic isolation, authentication, and the
no-client-supplied-results guarantee at the HTTP boundary.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.modules.patients.models import Patient


def _seg_url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/segmentation"


def _review_url(patient_id, analysis_id) -> str:
    return f"{_seg_url(patient_id)}/{analysis_id}/review"


async def _role_headers(db: AsyncSession, clinic_id, role: str) -> dict[str, str]:
    user = User(
        id=uuid4(),
        email=f"{role}-{uuid4().hex[:8]}@test.clinic",
        password_hash=hash_password("TestPass1234"),
        first_name=role.title(),
        last_name="User",
    )
    db.add(user)
    await db.flush()
    db.add(ClinicMembership(id=uuid4(), user_id=user.id, clinic_id=clinic_id, role=role))
    await db.commit()
    token = create_access_token(user.id, token_version=user.token_version)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_run_returns_pending_analysis(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    response = await client.post(_seg_url(test_patient.id), headers=auth_headers)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["review_status"] == "pending"
    assert body["provider"] == "arch-partition"
    assert body["is_clinical"] is False
    assert body["requires_review"] is True
    assert body["segmented_count"] == 32
    assert body["uncertain_count"] == 0
    assert len(body["teeth"]) == 32
    assert body["teeth"][0]["evidence"]["arch_region"] == "Q1-incisor"
    assert "non-clinical" in body["disclaimer"].lower()


@pytest.mark.asyncio
async def test_get_latest_after_run_and_404_before(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    assert (await client.get(_seg_url(test_patient.id), headers=auth_headers)).status_code == 404
    created = (await client.post(_seg_url(test_patient.id), headers=auth_headers)).json()["data"]
    latest = await client.get(_seg_url(test_patient.id), headers=auth_headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["id"] == created["id"]


@pytest.mark.asyncio
async def test_review_workflow_via_http(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    analysis_id = (await client.post(_seg_url(test_patient.id), headers=auth_headers)).json()[
        "data"
    ]["id"]
    response = await client.post(
        _review_url(test_patient.id, analysis_id),
        headers=auth_headers,
        json={"decision": "accepted", "note": "reviewed in staff meeting"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["review_status"] == "accepted"
    assert body["review_note"] == "reviewed in staff meeting"

    # Double review → 409.
    again = await client.post(
        _review_url(test_patient.id, analysis_id),
        headers=auth_headers,
        json={"decision": "rejected"},
    )
    assert again.status_code == 409

    # Scene summary now reports the decision.
    scene = await client.get(
        f"/api/v1/dental_3d/patients/{test_patient.id}/scene", headers=auth_headers
    )
    assert scene.json()["data"]["segmentation"]["review_status"] == "accepted"


@pytest.mark.asyncio
async def test_review_unknown_analysis_404(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    response = await client.post(
        _review_url(test_patient.id, uuid4()),
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_invalid_decision_422(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    analysis_id = (await client.post(_seg_url(test_patient.id), headers=auth_headers)).json()[
        "data"
    ]["id"]
    response = await client.post(
        _review_url(test_patient.id, analysis_id),
        headers=auth_headers,
        json={"decision": "final_diagnosis"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_readonly_assistant_cannot_run_or_review(
    client: AsyncClient, db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    headers = await _role_headers(db_session, test_clinic.id, "assistant")
    # Read access to a finished analysis is allowed…
    assert (await client.get(_seg_url(test_patient.id), headers=headers)).status_code == 404
    # …but write actions are forbidden.
    assert (await client.post(_seg_url(test_patient.id), headers=headers)).status_code == 403
    assert (
        await client.post(
            _review_url(test_patient.id, uuid4()), headers=headers, json={"decision": "accepted"}
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_hygienist_can_run_and_review(
    client: AsyncClient, db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    headers = await _role_headers(db_session, test_clinic.id, "hygienist")
    assert (await client.post(_seg_url(test_patient.id), headers=headers)).status_code == 201


@pytest.mark.asyncio
async def test_receptionist_fully_forbidden(
    client: AsyncClient, db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    headers = await _role_headers(db_session, test_clinic.id, "receptionist")
    assert (await client.get(_seg_url(test_patient.id), headers=headers)).status_code == 403
    assert (await client.post(_seg_url(test_patient.id), headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_cross_clinic_isolation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    other = Clinic(id=uuid4(), name="Other", tax_id="B00000000", address={}, settings={})
    db_session.add(other)
    await db_session.flush()
    stranger = Patient(
        id=uuid4(),
        clinic_id=other.id,
        first_name="Other",
        last_name="Clinic",
        email="stranger2@other.clinic",
        phone="+34600000001",
    )
    db_session.add(stranger)
    await db_session.commit()

    # The other clinic's patient is invisible (404, not a leak) — and
    # analyses can never be run or reviewed across clinics.
    assert (await client.post(_seg_url(stranger.id), headers=auth_headers)).status_code == 404
    assert (await client.get(_seg_url(stranger.id), headers=auth_headers)).status_code == 404
    assert (
        await client.post(
            _review_url(stranger.id, uuid4()), headers=auth_headers, json={"decision": "accepted"}
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_authentication_required(client: AsyncClient, test_patient: Patient) -> None:
    assert (await client.post(_seg_url(test_patient.id))).status_code == 401
    assert (await client.get(_seg_url(test_patient.id))).status_code == 401
    assert (
        await client.post(_review_url(test_patient.id, uuid4()), json={"decision": "accepted"})
    ).status_code == 401
