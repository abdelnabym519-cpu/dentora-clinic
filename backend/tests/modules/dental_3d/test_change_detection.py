"""Change Detection contract, deterministic comparison, and persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.case_intelligence.models import CaseSnapshotRecord
from app.modules.dental_3d.change_detection import (
    ChangeDetectionService,
    compare_snapshot_payloads,
)
from app.modules.dental_3d.change_detection_router import router
from app.modules.patients.models import Patient


def _snapshot(value: float, *, condition: str = "stable", frame_uid: str = "1.2.3") -> dict:
    return {
        "reference_frame": {
            "status": "available",
            "data": {
                "kind": "dicom_patient",
                "unit": "mm",
                "frame_of_reference_uid": frame_uid,
            },
        },
        "clinical_state": {
            "cbct": {
                "status": "available",
                "data": {
                    "lesion": {
                        "size_mm": value,
                        "condition": condition,
                        "updated_at": "ignored-provenance-timestamp",
                    }
                },
            }
        },
    }


def test_numeric_change_reports_delta_and_percentage() -> None:
    _, changes = compare_snapshot_payloads(_snapshot(2.1), _snapshot(3.4))

    assert len(changes) == 1
    change = changes[0]
    assert change.section == "cbct"
    assert change.path.endswith("lesion.size_mm")
    assert change.kind == "numeric"
    assert change.delta == pytest.approx(1.3)
    assert change.percent_change == 61.9


def test_categorical_change_is_reported_but_metadata_timestamp_is_ignored() -> None:
    _, changes = compare_snapshot_payloads(
        _snapshot(2.1, condition="stable"),
        _snapshot(2.1, condition="progressed"),
    )

    assert [(item.kind, item.path, item.before, item.after) for item in changes] == [
        (
            "categorical",
            "clinical_state.cbct.data.lesion.condition",
            "stable",
            "progressed",
        )
    ]


def test_zero_baseline_has_delta_without_undefined_percentage() -> None:
    _, changes = compare_snapshot_payloads(_snapshot(0.0), _snapshot(1.0))

    assert changes[0].delta == 1.0
    assert changes[0].percent_change is None


def test_incompatible_registration_fails_closed() -> None:
    with pytest.raises(ValueError, match="same patient reference frame"):
        compare_snapshot_payloads(
            _snapshot(2.1, frame_uid="1.2.3"),
            _snapshot(3.4, frame_uid="9.8.7"),
        )


def test_compare_endpoint_matches_longitudinal_contract() -> None:
    paths = {route.path for route in router.routes}
    assert "/cases/{patient_id}/compare" in paths


@pytest.mark.asyncio
@pytest.mark.storage_integration
async def test_persisted_snapshots_are_compared_with_tenant_scope(
    db_session: AsyncSession,
    test_patient: Patient,
) -> None:
    now = datetime.now(UTC)
    baseline = CaseSnapshotRecord(
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        snapshot_version=1,
        contract_version="1.0",
        source_digest="sha256:" + "1" * 64,
        snapshot_data=_snapshot(2.1),
        source_versions={"case_intelligence": "1"},
        generated_at=now,
    )
    followup = CaseSnapshotRecord(
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        snapshot_version=2,
        contract_version="1.0",
        source_digest="sha256:" + "2" * 64,
        snapshot_data=_snapshot(3.4),
        source_versions={"case_intelligence": "2"},
        generated_at=now,
    )
    db_session.add_all([baseline, followup])
    await db_session.commit()

    assert ChangeDetectionService.provider is not None
    result = await ChangeDetectionService.compare(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        baseline_version=1,
        followup_version=2,
    )

    assert result.reference_frame_uid == "1.2.3"
    assert result.change_count == 1
    assert result.changes[0].delta == pytest.approx(1.3)
    assert result.changes[0].percent_change == 61.9
    assert result.baseline.source_digest == baseline.source_digest
    assert result.followup.source_digest == followup.source_digest

    foreign_clinic_id = UUID(int=test_patient.clinic_id.int ^ 1)
    with pytest.raises(KeyError, match="snapshot_not_found"):
        await ChangeDetectionService.compare(
            db_session,
            clinic_id=foreign_clinic_id,
            patient_id=test_patient.id,
            baseline_version=1,
            followup_version=2,
        )
