"""Integration/security tests for Dentora Voice → ToolRegistry execution."""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.models import AgentAuditLog
from app.core.auth.models import Clinic, ClinicMembership
from app.modules.patients.models import Patient


async def _patient(
    db: AsyncSession,
    clinic_id,
    *,
    first_name: str,
    last_name: str,
    phone: str | None = None,
    email: str | None = None,
) -> Patient:
    patient = Patient(
        id=uuid4(),
        clinic_id=clinic_id,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        status="active",
    )
    db.add(patient)
    await db.commit()
    return patient


async def test_open_patient_executes_through_registry_and_redacts_audit(
    client,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    patient = await _patient(
        db_session,
        test_clinic.id,
        first_name="أحمد",
        last_name="محمد",
        phone="+201234567890",
        email="ahmed.patient@example.com",
    )

    response = await client.post(
        "/api/v1/voice/execute",
        headers=auth_headers,
        json={
            "transcript": "افتح حالة أحمد محمد",
            "context": {
                "route": "/patients",
                "viewer_open": False,
                "implant_planner_open": False,
            },
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["state"] == "success"
    assert result["steps"][0]["command"] == "OPEN_PATIENT"
    assert result["steps"][0]["ui_action"]["action"] == "navigate"
    assert result["steps"][0]["ui_action"]["payload"]["route"] == f"/patients/{patient.id}"

    logs = list(
        (
            await db_session.execute(
                select(AgentAuditLog).where(AgentAuditLog.clinic_id == test_clinic.id)
            )
        ).scalars()
    )
    assert any(log.tool_name == "patients.search_patients" for log in logs)
    assert any(log.tool_name == "voice.ui_action" for log in logs)
    persisted = json.dumps(
        [{"arguments": log.tool_arguments, "result": log.result} for log in logs],
        ensure_ascii=False,
        default=str,
    )
    assert "أحمد" not in persisted
    assert "محمد" not in persisted
    assert "+201234567890" not in persisted
    assert "ahmed.patient@example.com" not in persisted
    assert str(patient.id) not in persisted


async def test_ambiguous_patient_stops_before_navigation(
    client,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    await _patient(db_session, test_clinic.id, first_name="Ahmed", last_name="Ali")
    await _patient(db_session, test_clinic.id, first_name="Ahmed", last_name="Hassan")

    response = await client.post(
        "/api/v1/voice/execute",
        headers=auth_headers,
        json={
            "transcript": "Open patient Ahmed",
            "context": {
                "route": "/patients",
                "viewer_open": False,
                "implant_planner_open": False,
            },
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["state"] == "clarification_required"
    assert result["steps"][0]["message"] == "ambiguous_patient"
    assert result["steps"][0]["ui_action"] is None
    assert len(result["steps"][0]["data"]["candidates"]) == 2


async def test_cross_tenant_patient_cannot_be_resolved(
    client,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    other_clinic = Clinic(
        id=uuid4(),
        name="Other Clinic",
        tax_id="B87654321",
        address={"street": "Other", "city": "Cairo"},
        settings={"slot_duration_min": 15},
    )
    db_session.add(other_clinic)
    await db_session.commit()
    await _patient(
        db_session,
        other_clinic.id,
        first_name="Private",
        last_name="Patient",
    )

    response = await client.post(
        "/api/v1/voice/execute",
        headers=auth_headers,
        json={
            "transcript": "Open patient Private Patient",
            "context": {
                "route": "/patients",
                "viewer_open": False,
                "implant_planner_open": False,
            },
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["state"] == "error"
    assert result["steps"][0]["message"] == "patient_not_found"


async def test_domain_permission_is_rechecked_at_tool_registry(
    client,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    patient = await _patient(db_session, test_clinic.id, first_name="Voice", last_name="Viewer")
    membership = await db_session.scalar(
        select(ClinicMembership).where(ClinicMembership.clinic_id == test_clinic.id)
    )
    assert membership is not None
    membership.role = "receptionist"
    await db_session.commit()

    response = await client.post(
        "/api/v1/voice/execute",
        headers=auth_headers,
        json={
            "transcript": "Show 3d",
            "context": {
                "route": f"/patients/{patient.id}",
                "patient_id": str(patient.id),
                "viewer_open": True,
                "implant_planner_open": False,
            },
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["state"] == "error"
    assert "permission denied: dental_3d.read" in result["steps"][0]["message"]


async def test_multi_step_stops_after_missing_cbct(
    client,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    await _patient(db_session, test_clinic.id, first_name="Ahmed", last_name="NoCbct")

    response = await client.post(
        "/api/v1/voice/execute",
        headers=auth_headers,
        json={
            "transcript": "Open patient Ahmed NoCbct and then show latest CBCT and then show the nerve",
            "context": {
                "route": "/patients",
                "viewer_open": False,
                "implant_planner_open": False,
            },
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert [step["command"] for step in result["steps"]] == ["OPEN_PATIENT", "OPEN_CBCT"]
    assert result["steps"][0]["ok"] is True
    assert result["steps"][1]["message"] == "cbct_not_available"


async def test_unsupported_repository_target_fails_closed(
    client,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    response = await client.post(
        "/api/v1/voice/execute",
        headers=auth_headers,
        json={
            "transcript": "قارن الفحص الحالي بالفحص السابق",
            "context": {
                "route": "/patients",
                "viewer_open": False,
                "implant_planner_open": False,
            },
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["state"] == "error"
    assert result["steps"][0]["command"] == "COMPARE_SCANS"
    assert "No scan-comparison" in result["steps"][0]["message"]
