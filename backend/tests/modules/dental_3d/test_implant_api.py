"""API lifecycle tests for deterministic implant planning."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dental_3d.implant_models import DentalImplantPlanRevision
from app.modules.dental_3d.models import DentalAlignmentResult
from app.modules.patients.models import Patient

FRAME = "2.25.62227709036452476721866742325628339408"


async def _accepted_alignment(db: AsyncSession, patient: Patient) -> DentalAlignmentResult:
    row = DentalAlignmentResult(
        clinic_id=patient.clinic_id,
        patient_id=patient.id,
        performed_by=None,
        status="accepted",
        algorithm="fixture-rigid",
        algorithm_version="1",
        transform={
            "matrix": [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        },
        source_frame={"id": "ios", "kind": "ios_mesh", "unit": "mm"},
        target_frame={
            "id": "dicom",
            "kind": "dicom_patient",
            "unit": "mm",
            "frame_of_reference_uid": FRAME,
        },
        provenance={
            "ios": {
                "identifier": "ios-fixture",
                "digest": "sha256:" + "a" * 64,
                "document_ids": [],
                "original_unit": "mm",
                "normalized_unit": "mm",
            },
            "cbct": {
                "identifier": "cbct-fixture",
                "digest": "sha256:" + "b" * 64,
                "document_ids": [],
                "original_unit": "mm",
                "normalized_unit": "mm",
            },
            "anatomy_model_id": "fixture",
            "anatomy_model_version": "1",
        },
        metrics={
            "initializer": "open3d_ransac",
            "source_point_count": 100,
            "target_point_count": 100,
            "feature_correspondence_count": 80,
            "inlier_correspondence_count": 70,
            "global_fitness": 0.8,
            "global_inlier_rmse_mm": 0.5,
            "icp_fitness": 0.9,
            "icp_inlier_rmse_mm": 0.3,
            "overlap_ratio": 0.8,
            "icp_iterations": 20,
            "icp_converged": True,
            "outlier_ratio": 0.1,
            "clinical_threshold_status": "CLINICAL_THRESHOLD_NOT_VALIDATED",
        },
        performed_at=datetime.now(UTC),
        reviewed_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    return row


def _candidate(center_z: float = 5.0) -> dict:
    return {
        "center": {"x": 0, "y": 0, "z": center_z},
        "axis": {"x": 0, "y": 0, "z": 1},
        "diameter_mm": 4.0,
        "length_mm": 10.0,
        "frame_of_reference_uid": FRAME,
        "unit": "mm",
        "dimension_source": "explicit-fixture",
    }


@pytest.mark.asyncio
async def test_plan_requires_current_accepted_prosthetic_target_for_acceptance_and_edits_revision(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    alignment = await _accepted_alignment(db_session, test_patient)
    base = f"/api/v1/dental_3d/patients/{test_patient.id}"

    snapshot = await client.get(f"{base}/implant-planning", headers=auth_headers)
    assert snapshot.status_code == 200
    assert snapshot.json()["data"]["prosthetic"]["status"] == "unavailable"

    created = await client.post(
        f"{base}/implant-plans",
        headers=auth_headers,
        json={"candidate": _candidate()},
    )
    assert created.status_code == 201
    plan = created.json()["data"]
    assert plan["status"] == "draft"
    assert plan["current_revision"]["revision_number"] == 1
    assert plan["current_revision"]["assessment"]["prosthetic_offset_mm"]["status"] == "UNAVAILABLE"
    assert (
        plan["current_revision"]["assessment"]["nerve_surface_to_centerline_mm"]["status"]
        == "UNAVAILABLE"
    )
    assert plan["current_revision"]["assessment"]["bone_axis_span_mm"]["status"] == "UNAVAILABLE"

    blocked = await client.post(
        f"{base}/implant-plans/{plan['id']}/review",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert blocked.status_code == 409

    target = await client.post(
        f"{base}/prosthetic-targets",
        headers=auth_headers,
        json={
            "alignment_id": str(alignment.id),
            "platform_center": {"x": 0, "y": 0, "z": 0},
            "axis": {"x": 0, "y": 0, "z": 1},
            "frame_of_reference_uid": FRAME,
            "source_type": "dentist_defined",
            "source_reference_space": "dicom_patient",
            "source_frame_of_reference_uid": FRAME,
            "source_method": "explicit_dentist_entry",
            "source_identifier": "fixture-target",
        },
    )
    assert target.status_code == 201
    target_data = target.json()["data"]
    assert target_data["review_status"] == "pending_review"

    reviewed_target = await client.post(
        f"{base}/prosthetic-targets/{target_data['id']}/review",
        headers=auth_headers,
        json={"decision": "accepted", "note": "fixture review"},
    )
    assert reviewed_target.status_code == 200
    assert reviewed_target.json()["data"]["review_status"] == "accepted"

    edited = await client.put(
        f"{base}/implant-plans/{plan['id']}",
        headers=auth_headers,
        json={"candidate": _candidate()},
    )
    assert edited.status_code == 200
    revised = edited.json()["data"]
    assert revised["status"] == "draft"
    assert revised["current_revision"]["revision_number"] == 2
    assert revised["reviewed_at"] is None
    assert revised["current_revision"]["assessment"]["prosthetic_offset_mm"]["value"] == 0
    assert revised["current_revision"]["assessment"]["prosthetic_axis_angle_deg"]["value"] == 0

    accepted = await client.post(
        f"{base}/implant-plans/{plan['id']}/review",
        headers=auth_headers,
        json={"decision": "accepted", "note": "dentist fixture acceptance"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["status"] == "accepted"

    edited_again = await client.put(
        f"{base}/implant-plans/{plan['id']}",
        headers=auth_headers,
        json={"candidate": _candidate(center_z=6)},
    )
    assert edited_again.status_code == 200
    third = edited_again.json()["data"]
    assert third["status"] == "draft"
    assert third["reviewed_at"] is None
    assert third["current_revision"]["revision_number"] == 3

    revision_count = await db_session.scalar(
        select(func.count())
        .select_from(DentalImplantPlanRevision)
        .where(DentalImplantPlanRevision.plan_id == UUID(plan["id"]))
    )
    assert revision_count == 3
