from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth.models import ClinicMembership
from app.modules.risk_engine.models import RiskResultRecord
from app.modules.risk_engine.service import RiskEngineService


@pytest.mark.asyncio
async def test_generate_is_append_only_traceable_and_dentist_reviewed(
    client,
    db_session,
    auth_headers,
    test_clinic,
    test_patient,
):
    first_response = await client.post(
        f"/api/v1/risk_engine/patients/{test_patient.id}", headers=auth_headers
    )
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()["data"]
    assert first["result_version"] == 1
    assert first["review_status"] == "pending_review"
    assert first["is_clinical"] is False
    assert first["requires_review"] is True
    assert first["advisory_only"] is True
    assert first["provenance"]["input_digest"].startswith("sha256:")
    assert first["provenance"]["result_digest"].startswith("sha256:")
    assert first["risk_map"]["synthetic_geometry"] is False

    second_response = await client.post(
        f"/api/v1/risk_engine/patients/{test_patient.id}", headers=auth_headers
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()["data"]
    assert second["result_version"] == 2
    assert second["provenance"]["input_digest"] == first["provenance"]["input_digest"]
    assert second["provenance"]["result_digest"] == first["provenance"]["result_digest"]

    rows = (
        await db_session.scalars(
            select(RiskResultRecord)
            .where(RiskResultRecord.patient_id == test_patient.id)
            .order_by(RiskResultRecord.result_version)
        )
    ).all()
    assert [row.result_version for row in rows] == [1, 2]

    review = await client.post(
        f"/api/v1/risk_engine/results/{rows[-1].id}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert review.status_code == 403

    membership = await db_session.scalar(
        select(ClinicMembership).where(ClinicMembership.clinic_id == test_clinic.id)
    )
    membership.role = "dentist"
    await db_session.commit()
    review = await client.post(
        f"/api/v1/risk_engine/results/{rows[-1].id}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert review.status_code == 200, review.text
    reviewed = review.json()["data"]
    assert reviewed["review_status"] == "accepted"
    assert reviewed["reviewed_by"] is not None
    assert reviewed["is_clinical"] is False


@pytest.mark.asyncio
async def test_tenant_isolation_and_review_is_single_transition(
    client,
    db_session,
    auth_headers,
    test_clinic,
    test_patient,
):
    response = await client.post(
        f"/api/v1/risk_engine/patients/{test_patient.id}", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    row = await db_session.scalar(
        select(RiskResultRecord).where(RiskResultRecord.patient_id == test_patient.id)
    )
    assert row is not None

    with pytest.raises(KeyError):
        await RiskEngineService.get_latest(
            db_session,
            clinic_id=uuid4(),
            patient_id=test_patient.id,
        )

    membership = await db_session.scalar(
        select(ClinicMembership).where(ClinicMembership.clinic_id == test_clinic.id)
    )
    membership.role = "dentist"
    await db_session.commit()
    first_review = await client.post(
        f"/api/v1/risk_engine/results/{row.id}/review",
        headers=auth_headers,
        json={"decision": "rejected"},
    )
    assert first_review.status_code == 200, first_review.text
    second_review = await client.post(
        f"/api/v1/risk_engine/results/{row.id}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert second_review.status_code == 409
