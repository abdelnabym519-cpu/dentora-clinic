"""Domain contract tests for the dental_3d schemas.

Phase 1 contract invariants:
- FDI notation is the only accepted tooth numbering (odontogram is the
  source of truth for tooth identity — never duplicated).
- Mesh descriptors are source-agnostic but Phase 1 only produces
  ``synthetic`` / ``procedural``.
- Segmentation results cannot be client-supplied (future capability).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.schemas import (
    DentalMesh,
    DentalScene,
    DentalSceneUpdate,
    SegmentationResult,
    Tooth3D,
)


class TestTooth3D:
    def test_defaults_are_healthy_permanent_synthetic(self) -> None:
        tooth = Tooth3D(tooth_number=16)
        assert tooth.present is True
        assert tooth.condition == "healthy"
        assert tooth.visible is True
        assert tooth.color is None
        assert tooth.mesh.source == "synthetic"
        assert tooth.mesh.format == "procedural"
        assert tooth.mesh.document_id is None

    @pytest.mark.parametrize("number", [11, 18, 21, 48, 51, 85])
    def test_accepts_valid_fdi_numbers(self, number: int) -> None:
        assert Tooth3D(tooth_number=number).tooth_number == number

    @pytest.mark.parametrize("number", [0, 8, 10, 49, 50, 90, 99, 100])
    def test_rejects_invalid_fdi_numbers(self, number: int) -> None:
        with pytest.raises(ValidationError):
            Tooth3D(tooth_number=number)

    def test_rejects_non_hex_color_override(self) -> None:
        with pytest.raises(ValidationError):
            Tooth3D(tooth_number=16, color="red")

    def test_accepts_hex_color_override(self) -> None:
        assert Tooth3D(tooth_number=16, color="#EF4444").color == "#EF4444"


class TestDentalMesh:
    def test_rejects_unknown_source(self) -> None:
        with pytest.raises(ValidationError):
            DentalMesh(source="cbct_v2")

    def test_rejects_unknown_format(self) -> None:
        with pytest.raises(ValidationError):
            DentalMesh(format="ply")

    def test_vertex_count_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            DentalMesh(vertex_count=-1)


class TestSegmentationResult:
    def test_default_is_not_available(self) -> None:
        result = SegmentationResult()
        assert result.status == "not_available"
        assert result.method is None
        assert result.teeth_found == 0
        assert result.performed_at is None


class TestDentalSceneUpdate:
    def test_rejects_completed_segmentation(self) -> None:
        with pytest.raises(ValidationError):
            DentalSceneUpdate(
                teeth=[Tooth3D(tooth_number=16)],
                segmentation=SegmentationResult(status="completed", teeth_found=32),
            )

    def test_accepts_placeholder_segmentation(self) -> None:
        payload = DentalSceneUpdate(
            teeth=[],
            segmentation=SegmentationResult(status="not_available"),
        )
        assert payload.segmentation is not None
        assert payload.segmentation.status == "not_available"


class TestDentalScene:
    def test_teeth_cap_matches_fdi_universe(self) -> None:
        # 32 permanent + 20 deciduous teeth max — the FDI universe.
        with pytest.raises(ValidationError):
            DentalScene(teeth=[Tooth3D(tooth_number=11) for _ in range(53)])

    def test_empty_scene_is_valid(self) -> None:
        scene = DentalScene()
        assert scene.generator == "synthetic"
        assert scene.teeth == []
