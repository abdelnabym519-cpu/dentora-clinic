"""Change Detection contract and deterministic comparison tests."""

from __future__ import annotations

import pytest

from app.modules.dental_3d.change_detection import compare_snapshot_payloads
from app.modules.dental_3d.change_detection_router import router


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
