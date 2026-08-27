"""API tests for the Phase 4 nerve-detection endpoints.

Exercises the mounted router at ``/api/v1/dental_3d/`` through the
ASGI client: run → latest → review workflow, RBAC boundaries
(write-only actions), clinic isolation, authentication, the scene
summary, and the no-client-supplied-results guarantee at the HTTP
boundary.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.modules.dental_3d.nerve import (
    NerveDetectionRequest,
    NerveDetectionResult,
    NerveModelProvenance,
)
from app.modules.patients.models import Patient


class _ReviewableProvider:
    name = "api-stub"
    input_kind = "cbct_series"

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
        return NerveDetectionResult(
            status="no_detection",
            provider=self.name,
            method="test-only",
            input_kind="cbct_series",
            requires_review=True,
            provenance=NerveModelProvenance(
                model_id="stub",
                model_version="1",
                adapter="test",
                input_digest="sha256:" + "a" * 64,
                study_instance_uid="1.2.3",
                series_instance_uid="1.2.3.1",
                frame_of_reference_uid="1.2.3.2",
            ),
            performed_at=request.performed_at,
        )


def _reviewable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.dental_3d.infrastructure.default_nerve_provider",
        lambda _db: _ReviewableProvider(),
    )


def _nerve_url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/nerve-detection"


def _review_url(patient_id, analysis_id) -> str:
    return f"{_nerve_url(patient_id)}/{analysis_id}/review"


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
    response = await client.post(_nerve_url(test_patient.id), headers=auth_headers)
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["review_status"] == "not_applicable"
    assert body["provider"] == "cbct-model-service"
    assert body["status"] == "failed"
    assert body["is_clinical"] is False
    assert body["requires_review"] is False
    assert body["pathway_count"] == 0
    assert body["failure"]["code"] == "invalid_input"
    assert "verification" in body["disclaimer"].lower()


@pytest.mark.asyncio
async def test_get_latest_after_run_and_404_before(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    assert (await client.get(_nerve_url(test_patient.id), headers=auth_headers)).status_code == 404
    created = (await client.post(_nerve_url(test_patient.id), headers=auth_headers)).json()["data"]
    latest = await client.get(_nerve_url(test_patient.id), headers=auth_headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["id"] == created["id"]


@pytest.mark.asyncio
async def test_review_workflow_via_http(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reviewable(monkeypatch)
    analysis_id = (await client.post(_nerve_url(test_patient.id), headers=auth_headers)).json()[
        "data"
    ]["id"]
    response = await client.post(
        _review_url(test_patient.id, analysis_id),
        headers=auth_headers,
        json={"decision": "accepted", "note": "checked with the radiograph"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["review_status"] == "accepted"
    assert body["review_note"] == "checked with the radiograph"

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
    assert scene.json()["data"]["nerve_detection"]["review_status"] == "accepted"


@pytest.mark.asyncio
async def test_scene_summary_defaults_to_not_available(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    scene = await client.get(
        f"/api/v1/dental_3d/patients/{test_patient.id}/scene", headers=auth_headers
    )
    assert scene.status_code == 200
    summary = scene.json()["data"]["nerve_detection"]
    assert summary["status"] == "not_available"
    assert summary["non_clinical"] is True


@pytest.mark.asyncio
async def test_client_cannot_supply_completed_detection(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    scene = (
        await client.get(
            f"/api/v1/dental_3d/patients/{test_patient.id}/scene", headers=auth_headers
        )
    ).json()["data"]
    payload = {
        "teeth": scene["teeth"],
        "nerve_detection": {
            "status": "completed",
            "provider": "my-laptop",
            "pathway_count": 2,
        },
    }
    response = await client.put(
        f"/api/v1/dental_3d/patients/{test_patient.id}/scene",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 422  # rejected — server-side analysis only


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
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reviewable(monkeypatch)
    analysis_id = (await client.post(_nerve_url(test_patient.id), headers=auth_headers)).json()[
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
    assert (await client.get(_nerve_url(test_patient.id), headers=headers)).status_code == 404
    # …but write actions are forbidden.
    assert (await client.post(_nerve_url(test_patient.id), headers=headers)).status_code == 403
    assert (
        await client.post(
            _review_url(test_patient.id, uuid4()), headers=headers, json={"decision": "accepted"}
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_hygienist_can_run(
    client: AsyncClient, db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    headers = await _role_headers(db_session, test_clinic.id, "hygienist")
    assert (await client.post(_nerve_url(test_patient.id), headers=headers)).status_code == 201


@pytest.mark.asyncio
async def test_receptionist_fully_forbidden(
    client: AsyncClient, db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    headers = await _role_headers(db_session, test_clinic.id, "receptionist")
    assert (await client.get(_nerve_url(test_patient.id), headers=headers)).status_code == 403
    assert (await client.post(_nerve_url(test_patient.id), headers=headers)).status_code == 403


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
        email="stranger-nerve@other.clinic",
        phone="+34600000002",
    )
    db_session.add(stranger)
    await db_session.commit()

    # The other clinic's patient is invisible (404, not a leak) — and
    # analyses can never be run or reviewed across clinics.
    assert (await client.post(_nerve_url(stranger.id), headers=auth_headers)).status_code == 404
    assert (await client.get(_nerve_url(stranger.id), headers=auth_headers)).status_code == 404
    assert (
        await client.post(
            _review_url(stranger.id, uuid4()), headers=auth_headers, json={"decision": "accepted"}
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_authentication_required(client: AsyncClient, test_patient: Patient) -> None:
    assert (await client.post(_nerve_url(test_patient.id))).status_code == 401
    assert (await client.get(_nerve_url(test_patient.id))).status_code == 401
    assert (
        await client.post(_review_url(test_patient.id, uuid4()), json={"decision": "accepted"})
    ).status_code == 401
