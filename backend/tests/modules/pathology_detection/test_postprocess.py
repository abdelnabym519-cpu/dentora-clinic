"""Unit tests for the geometric FDI enumeration + helpers."""

from __future__ import annotations

import pytest

from app.modules.pathology_detection.constants import (
    DIAGNOSIS_CARIES,
    DIAGNOSIS_IMPACTED_TOOTH,
    quadrant_of_fdi,
    summary_counts,
)
from app.modules.pathology_detection.engine.base import DetectedFinding
from app.modules.pathology_detection.engine.postprocess import (
    enumerate_fdi,
    filter_by_confidence,
    quadrant_for_center,
)


def _f(
    diagnosis: str, x1: float, y1: float, x2: float, y2: float, conf: float = 0.9
) -> DetectedFinding:
    return DetectedFinding(diagnosis=diagnosis, confidence=conf, x1=x1, y1=y1, x2=x2, y2=y2)


def test_quadrant_for_center_maps_all_four() -> None:
    assert quadrant_for_center(0.2, 0.2) == 1  # top-left = patient right upper
    assert quadrant_for_center(0.8, 0.2) == 2  # top-right
    assert quadrant_for_center(0.8, 0.8) == 3  # bottom-right
    assert quadrant_for_center(0.2, 0.8) == 4  # bottom-left


def test_enumerate_fdi_numbering_per_quadrant() -> None:
    # Top-left quadrant, three boxes ordered left → right.
    findings = [
        _f(DIAGNOSIS_CARIES, 0.10, 0.10, 0.20, 0.30),
        _f(DIAGNOSIS_CARIES, 0.25, 0.10, 0.35, 0.30),
        _f(DIAGNOSIS_CARIES, 0.40, 0.10, 0.50, 0.30),
    ]
    enriched = enumerate_fdi(findings)
    # FDI position 1 is nearest the midline (largest x in this quadrant).
    assert [e.tooth_number for e in enriched] == [11, 12, 13]
    assert all(e.quadrant == 1 for e in enriched)


def test_enumerate_fdi_upper_right_ascends_from_midline() -> None:
    findings = [
        _f(DIAGNOSIS_CARIES, 0.55, 0.10, 0.65, 0.30),
        _f(DIAGNOSIS_CARIES, 0.80, 0.10, 0.90, 0.30),
    ]
    enriched = enumerate_fdi(findings)
    assert [e.tooth_number for e in enriched] == [21, 22]


def test_filter_by_confidence_sorts_desc() -> None:
    findings = [
        _f(DIAGNOSIS_CARIES, 0, 0, 1, 1, conf=0.5),
        _f(DIAGNOSIS_CARIES, 0, 0, 1, 1, conf=0.9),
        _f(DIAGNOSIS_CARIES, 0, 0, 1, 1, conf=0.2),
    ]
    kept = filter_by_confidence(findings, 0.35)
    assert [round(f.confidence, 1) for f in kept] == [0.9, 0.5]


def test_summary_counts_zero_filled() -> None:
    counts = summary_counts(
        [
            {"diagnosis": DIAGNOSIS_CARIES},
            {"diagnosis": DIAGNOSIS_CARIES},
            {"diagnosis": DIAGNOSIS_IMPACTED_TOOTH},
        ]
    )
    assert counts == {
        "caries": 2,
        "deep_caries": 0,
        "periapical_lesion": 0,
        "impacted_tooth": 1,
    }


def test_quadrant_of_fdi_validation() -> None:
    assert quadrant_of_fdi(48) == 4
    with pytest.raises(ValueError):
        quadrant_of_fdi(50)
