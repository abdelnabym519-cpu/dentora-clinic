"""API + persistence tests for the orthodontic planning module.

Exercises the full surface against the real app and Postgres:
assessment → plan → review lifecycle, RBAC, and every fail-closed path
(insufficient data, provider unavailable, provider crash, unsafe
provider output refused + audited). The provider is injected with
controllables — no external model is ever needed.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.core.events import event_bus
from app.modules.orthodontic_planning import service as service_module
from app.modules.orthodontic_planning.constants import CONSTRAINTS_VERSION
from app.modules.orthodontic_planning.domain import (
    Movement,
    PlannerCase,
    Stage,
)
from app.modules.orthodontic_planning.planner.base import (
    PlanSuggestion,
    ProviderUnavailableError,
)
from app.modules.patients.models import Patient

from .helpers import complete_measurements, seed_odontogram

pytestmark = pytest.mark.asyncio

PLAN_URL = "/api/v1/orthodontic_planning"


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def bind(self, event_type: str):
        def handler(data: dict) -> None:
            self.events.append((event_type, data))

        return handler


@pytest.fixture
def event_sink():
    sink = RecordingEventSink()
    subscriptions = [
        (
            "orthodontic_planning.proposal_created",
            sink.bind("orthodontic_planning.proposal_created"),
        ),
        (
            "orthodontic_planning.proposal_reviewed",
            sink.bind("orthodontic_planning.proposal_reviewed"),
        ),
        (
            "orthodontic_planning.plan_refused",
            sink.bind("orthodontic_planning.plan_refused"),
        ),
    ]
    for event_type, handler in subscriptions:
        event_bus.subscribe(event_type, handler)
    yield sink
    for event_type, handler in subscriptions:
        event_bus.unsubscribe(event_type, handler)


async def _create_assessment(
    client: AsyncClient,
    auth_headers: dict[str, str],
    patient_id: str,
    **overrides,
) -> dict:
    response = await client.post(
        f"{PLAN_URL}/patients/{patient_id}/assessments",
        headers=auth_headers,
        json=complete_measurements(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _seed_plannable_case(
    db: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_patient: Patient,
) -> dict:
    await seed_odontogram(db, clinic_id=test_patient.clinic_id, patient_id=test_patient.id)
    return await _create_assessment(client, auth_headers, str(test_patient.id))


# --- capabilities ------------------------------------------------------------------


async def test_capabilities_reports_provider_and_envelope(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic
) -> None:
    response = await client.get(f"{PLAN_URL}/capabilities", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "heuristic_v1"
    assert data["constraints_version"] == CONSTRAINTS_VERSION
    assert data["decision_support_only"] is True
    assert data["deterministic"] is True
    assert data["approval_required"] is True
    assert "overjet_mm" in data["required_measurements"]
    assert data["movement_limits"]["distalization"]["per_stage"] == 0.5


# --- assessment flow ------------------------------------------------------------------


async def test_assessment_captures_dentition_snapshot_and_sufficiency(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    await seed_odontogram(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        rotated=(11,),
        missing=(16,),
        deciduous=(55,),
    )
    response = await client.post(
        f"{PLAN_URL}/patients/{test_patient.id}/assessments",
        headers=auth_headers,
        json=complete_measurements(),
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]

    snapshot = data["dentition_snapshot"]
    teeth = {t["tooth_number"]: t for t in snapshot["teeth"]}
    assert teeth[11]["is_rotated"] is True
    assert teeth[16]["present"] is False
    assert teeth[55]["dentition"] == "deciduous"

    sufficiency = data["data_sufficiency"]
    assert sufficiency["is_plannable"] is True
    assert sufficiency["charted_permanent"] == 31
    assert sufficiency["score"] == 1.0

    # List + detail + 404 paths.
    listing = await client.get(
        f"{PLAN_URL}/patients/{test_patient.id}/assessments", headers=auth_headers
    )
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1
    detail = await client.get(f"{PLAN_URL}/assessments/{data['id']}", headers=auth_headers)
    assert detail.status_code == 200
    missing_patient = await client.post(
        f"{PLAN_URL}/patients/{uuid4()}/assessments",
        headers=auth_headers,
        json=complete_measurements(),
    )
    assert missing_patient.status_code == 404


async def test_assessment_range_validation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    await seed_odontogram(db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id)
    response = await client.post(
        f"{PLAN_URL}/patients/{test_patient.id}/assessments",
        headers=auth_headers,
        json=complete_measurements(overjet_mm=99.0),
    )
    assert response.status_code == 422  # pydantic bound


# --- plan flow ------------------------------------------------------------------


async def test_plan_generation_review_lifecycle_and_events(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
    event_sink: RecordingEventSink,
) -> None:
    assessment = await _seed_plannable_case(db_session, client, auth_headers, test_patient)
    response = await client.post(
        f"{PLAN_URL}/assessments/{assessment['id']}/plan",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 201, response.text
    proposal = response.json()["data"]

    assert proposal["status"] == "draft"
    assert proposal["provider"] == "heuristic_v1"
    assert proposal["stage_count"] >= 1
    assert proposal["planned_months"] >= 1
    assert 0.0 <= proposal["score"] <= 1.0
    assert 0.0 < proposal["confidence"] <= 0.9
    assert proposal["constraint_report"]["is_valid"] is True
    assert proposal["hard_violation_count"] == 0
    assert proposal["stages"], "plan must contain stages"
    for stage in proposal["stages"]:
        assert stage["label"]
        for movement in stage["movements"]:
            assert movement["magnitude"] > 0

    # Audit event for creation.
    assert any(
        etype == "orthodontic_planning.proposal_created"
        and payload["proposal_id"] == proposal["id"]
        for etype, payload in event_sink.events
    )

    # Review: approve.
    review = await client.post(
        f"{PLAN_URL}/proposals/{proposal['id']}/review",
        headers=auth_headers,
        json={"decision": "approved", "note": "clinically reasonable"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["data"]["status"] == "approved"
    assert any(
        etype == "orthodontic_planning.proposal_reviewed" and payload["decision"] == "approved"
        for etype, payload in event_sink.events
    )

    # Reviewing again is a 409 — the lifecycle is draft → decided, once.
    second = await client.post(
        f"{PLAN_URL}/proposals/{proposal['id']}/review",
        headers=auth_headers,
        json={"decision": "rejected"},
    )
    assert second.status_code == 409

    # Detail reflects the review.
    detail = await client.get(f"{PLAN_URL}/proposals/{proposal['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "approved"

    # Rejection path on a second proposal.
    second_plan = await client.post(
        f"{PLAN_URL}/assessments/{assessment['id']}/plan", headers=auth_headers, json={}
    )
    assert second_plan.status_code == 201
    reject = await client.post(
        f"{PLAN_URL}/proposals/{second_plan.json()['data']['id']}/review",
        headers=auth_headers,
        json={"decision": "rejected", "note": "insufficient anchorage in my judgment"},
    )
    assert reject.status_code == 200
    assert reject.json()["data"]["status"] == "rejected"

    # Delete.
    deleted = await client.delete(
        f"{PLAN_URL}/proposals/{second_plan.json()['data']['id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204
    gone = await client.get(
        f"{PLAN_URL}/proposals/{second_plan.json()['data']['id']}",
        headers=auth_headers,
    )
    assert gone.status_code == 404


async def test_plan_fails_closed_on_undercharted_odontogram(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    # Only 10 permanent teeth charted → planning must refuse with the gap list.
    await seed_odontogram(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        teeth=(11, 12, 21, 22, 31, 32, 41, 42, 16, 26),
    )
    assessment = await _create_assessment(client, auth_headers, str(test_patient.id))
    assert assessment["data_sufficiency"]["is_plannable"] is False

    response = await client.post(
        f"{PLAN_URL}/assessments/{assessment['id']}/plan", headers=auth_headers, json={}
    )
    assert response.status_code == 422
    message = response.json()["message"]
    assert "Case data insufficient" in message
    assert "odontogram" in message

    # Nothing persisted.
    proposals = await client.get(
        f"{PLAN_URL}/patients/{test_patient.id}/proposals", headers=auth_headers
    )
    assert proposals.json()["data"] == []


async def test_plan_fails_closed_on_provider_unavailable(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = await _seed_plannable_case(db_session, client, auth_headers, test_patient)
    monkeypatch.setattr(
        service_module,
        "get_provider",
        lambda: (_ for _ in ()).throw(ProviderUnavailableError("provider not provisioned")),
    )
    response = await client.post(
        f"{PLAN_URL}/assessments/{assessment['id']}/plan", headers=auth_headers, json={}
    )
    assert response.status_code == 503
    assert "provider not provisioned" in response.json()["message"]


async def test_plan_fails_closed_on_provider_crash(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = await _seed_plannable_case(db_session, client, auth_headers, test_patient)

    class ExplodingProvider:
        name = "exploding"
        version = "0"

        def propose_plan(self, case: PlannerCase) -> PlanSuggestion:
            raise RuntimeError("model exploded")

    monkeypatch.setattr(service_module, "get_provider", lambda: ExplodingProvider())
    response = await client.post(
        f"{PLAN_URL}/assessments/{assessment['id']}/plan", headers=auth_headers, json={}
    )
    assert response.status_code == 503


async def test_unsafe_provider_output_is_refused_audited_and_not_persisted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
    monkeypatch: pytest.MonkeyPatch,
    event_sink: RecordingEventSink,
) -> None:
    # Chart a full dentition with tooth 46 missing.
    await seed_odontogram(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        missing=(46,),
    )
    assessment = await _create_assessment(client, auth_headers, str(test_patient.id))

    class UnsafeProvider:
        """Simulates a learned policy proposing movement on a missing tooth."""

        name = "unsafe_learned"
        version = "0.0.1"

        def propose_plan(self, case: PlannerCase) -> PlanSuggestion:
            return PlanSuggestion(
                stages=(
                    Stage(
                        label="unsafe",
                        movements=(
                            Movement(46, "distalization", 0.5),  # 46 is charted missing
                        ),
                    ),
                ),
                provider=self.name,
                provider_version=self.version,
                score=0.9,
                confidence=0.99,
            )

    monkeypatch.setattr(service_module, "get_provider", lambda: UnsafeProvider())
    response = await client.post(
        f"{PLAN_URL}/assessments/{assessment['id']}/plan", headers=auth_headers, json={}
    )
    assert response.status_code == 422
    message = response.json()["message"]
    assert "deterministic safety gate" in message
    assert "H_MISSING_TOOTH" in message
    assert "not saved" in message

    # Refusal audited, plan NOT persisted.
    assert any(
        etype == "orthodontic_planning.plan_refused"
        and "H_MISSING_TOOTH" in payload["hard_violations"]
        for etype, payload in event_sink.events
    )
    proposals = await client.get(
        f"{PLAN_URL}/patients/{test_patient.id}/proposals", headers=auth_headers
    )
    assert proposals.json()["data"] == []


# --- RBAC ---------------------------------------------------------------------------


async def _receptionist_headers(db: AsyncSession, test_clinic) -> dict[str, str]:
    user = User(
        email="reception@example.com",
        password_hash=hash_password("TestPass1234"),
        first_name="Recep",
        last_name="Tionist",
    )
    db.add(user)
    await db.flush()
    db.add(
        ClinicMembership(
            id=uuid4(),
            user_id=user.id,
            clinic_id=test_clinic.id,
            role="receptionist",
        )
    )
    await db.commit()
    token = create_access_token(user.id, token_version=user.token_version)
    return {"Authorization": f"Bearer {token}"}


async def test_receptionist_cannot_read_or_write(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic,
    test_patient: Patient,
) -> None:
    receptionist = await _receptionist_headers(db_session, test_clinic)
    for_read = await client.get(f"{PLAN_URL}/capabilities", headers=receptionist)
    assert for_read.status_code == 403
    for_write = await client.post(
        f"{PLAN_URL}/patients/{test_patient.id}/assessments",
        headers=receptionist,
        json=complete_measurements(),
    )
    assert for_write.status_code == 403


async def test_cross_clinic_isolation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic,
    test_patient: Patient,
) -> None:
    """A patient in another clinic is invisible (tenancy guard)."""
    from app.core.auth.models import Clinic

    other_clinic = Clinic(
        id=uuid4(),
        name="Other Clinic",
        tax_id="X99999999",
        address={"street": "Elsewhere", "city": "Madrid"},
        settings={},
    )
    db_session.add(other_clinic)
    foreign_patient = Patient(
        id=uuid4(),
        clinic_id=other_clinic.id,
        first_name="Foreign",
        last_name="Patient",
    )
    db_session.add(foreign_patient)
    await db_session.commit()

    response = await client.get(
        f"{PLAN_URL}/patients/{foreign_patient.id}/assessments",
        headers=auth_headers,
    )
    assert response.status_code == 404
