from __future__ import annotations

import numpy as np

from app.postprocess import ImageGeometry, extract_canal_findings


def _geometry() -> ImageGeometry:
    return ImageGeometry(
        size_xyz=(40, 40, 20),
        spacing_xyz=(0.5, 0.5, 0.5),
        origin_lps=(0.0, 0.0, 0.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    )


def test_two_bilateral_components_become_left_and_right_paths() -> None:
    seg = np.zeros((20, 40, 40), dtype=np.uint8)
    for z in range(4, 16):
        for y in range(10, 14):
            seg[z, y, 6:10] = 5
            seg[z, y + 10, 30:34] = 5

    result = extract_canal_findings(seg, _geometry(), confidence=0.91, min_component_voxels=20)

    assert result.status == "detected"
    assert result.significant_component_count == 2
    assert [item.side for item in result.findings] == ["right", "left"]
    assert all(len(item.points_mm) >= 2 for item in result.findings)
    assert all(item.confidence == 0.91 for item in result.findings)


def test_single_component_is_uncertain() -> None:
    seg = np.zeros((20, 40, 40), dtype=np.uint8)
    seg[4:16, 10:14, 6:10] = 5
    result = extract_canal_findings(seg, _geometry(), confidence=0.9, min_component_voxels=20)
    assert result.status == "uncertain"
    assert len(result.findings) == 1
    assert result.findings[0].side == "right"


def test_low_confidence_is_uncertain_and_empty_is_no_detection() -> None:
    seg = np.zeros((20, 40, 40), dtype=np.uint8)
    seg[4:16, 10:14, 6:10] = 5
    seg[4:16, 20:24, 30:34] = 5
    assert extract_canal_findings(seg, _geometry(), confidence=0.4, min_component_voxels=20).status == "uncertain"
    empty = np.zeros_like(seg)
    result = extract_canal_findings(empty, _geometry(), confidence=0.0, min_component_voxels=20)
    assert result.status == "no_detection"
    assert result.findings == ()
