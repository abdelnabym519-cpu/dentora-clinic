"""Domain/contract tests for Phase 4 nerve detection.

Covers:
- safety invariants fixed by the contracts (``is_clinical=False``,
  ``requires_review=True`` cannot be forged)
- pathway + proximity validation (FDI, confidence bounds, distance
  bounds, warning literals, polyline arity)
- the deterministic canonical-mandible provider behind the port
- left/right anatomy, confidence with/without scan geometry
- AI-estimated proximity gradient and closest-point indices
- the port is a real seam (stubs satisfy it; determinism across calls)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.infrastructure import (
    NERVE_MM_PER_UNIT,
    CanonicalMandibleNerveProvider,
    default_nerve_provider,
)
from app.modules.dental_3d.nerve import (
    CONFIDENCE_HIGH,
    PROXIMITY_MAX_MM,
    PROXIMITY_NEAR_MM,
    PROXIMITY_WATCH_MM,
    NerveDetectionProvider,
    NerveDetectionRequest,
    NerveDetectionResult,
    NerveEvidence,
    NervePathPoint,
    NervePathway,
    ToothNerveProximity,
)
from app.modules.dental_3d.schemas import DentalMesh, Tooth3D

PERMANENT = sorted(
    [int(f"{q}{u}") for q in (1, 2) for u in range(1, 9)]
    + [int(f"{q}{u}") for q in (3, 4) for u in range(1, 9)]
)
LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]


def _request(
    teeth: list[Tooth3D] | None = None, meshes: list[DentalMesh] | None = None
) -> NerveDetectionRequest:
    return NerveDetectionRequest(
        clinic_id=uuid4(),
        patient_id=uuid4(),
        teeth=teeth
        if teeth is not None
        else [Tooth3D(tooth_number=n, present=True, condition="healthy") for n in PERMANENT],
        meshes=meshes or [],
        performed_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )


def _mesh() -> DentalMesh:
    return DentalMesh(
        source="intraoral_scan",
        format="stl",
        document_id=uuid4(),
        label="scan",
        file_size=1024,
        uploaded_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        url="/api/v1/media/documents/x/download",
    )


# ---------------------------------------------------------------------------
# Contract invariants
# ---------------------------------------------------------------------------


def test_result_cannot_claim_clinical_or_skip_review() -> None:
    result = NerveDetectionResult(provider="p", method="m", performed_at=datetime.now(UTC))
    assert result.is_clinical is False
    assert result.requires_review is True
    # The literals make forging impossible, not just discouraged.
    with pytest.raises(ValidationError):
        NerveDetectionResult(
            provider="p", method="m", performed_at=datetime.now(UTC), is_clinical=True
        )
    with pytest.raises(ValidationError):
        NerveDetectionResult(
            provider="p", method="m", performed_at=datetime.now(UTC), requires_review=False
        )


def test_proximity_rejects_invalid_fdi() -> None:
    with pytest.raises(ValidationError):
        ToothNerveProximity(
            tooth_number=39,  # nonexistent FDI
            side="left",
            distance_mm=3.0,
            closest_point_index=0,
            warning="watch",
            confidence=0.6,
        )


def test_proximity_confidence_and_distance_bounds() -> None:
    base = dict(
        tooth_number=36, side="left", closest_point_index=0, warning="watch", confidence=0.6
    )
    with pytest.raises(ValidationError):
        ToothNerveProximity(**base | {"distance_mm": -0.1})
    with pytest.raises(ValidationError):
        ToothNerveProximity(**base | {"distance_mm": 100.1})
    with pytest.raises(ValidationError):
        ToothNerveProximity(**base | {"confidence": 1.5})
    with pytest.raises(ValidationError):
        ToothNerveProximity(**base | {"warning": "unsafe"})  # not a clinical verdict literal
    with pytest.raises(ValidationError):
        ToothNerveProximity(**base | {"closest_point_index": -1})


def test_pathway_requires_polyline_and_valid_side() -> None:
    ok = NervePathway(
        side="left",
        status="detected",
        confidence=0.75,
        points=[NervePathPoint(x=1, y=0, z=0), NervePathPoint(x=2, y=0, z=0)],
        evidence=NerveEvidence(basis="anatomical_model"),
    )
    assert ok.side == "left"
    with pytest.raises(ValidationError):
        NervePathway(  # a single point is not a pathway
            side="left",
            status="detected",
            confidence=0.75,
            points=[NervePathPoint(x=1, y=0, z=0)],
        )
    with pytest.raises(ValidationError):
        NervePathway(
            side="middle",  # anatomy is left/right
            status="detected",
            confidence=0.75,
            points=[NervePathPoint(x=1, y=0, z=0), NervePathPoint(x=2, y=0, z=0)],
        )
    with pytest.raises(ValidationError):
        NervePathway(
            side="left",
            status="detected",
            confidence=1.2,
            points=[NervePathPoint(x=1, y=0, z=0), NervePathPoint(x=2, y=0, z=0)],
        )


def test_evidence_basis_is_bounded() -> None:
    with pytest.raises(ValidationError):
        NerveEvidence(basis="patient_ct")  # Phase 4 has no such basis


# ---------------------------------------------------------------------------
# The port is a real seam
# ---------------------------------------------------------------------------


def test_provider_satisfies_port() -> None:
    assert isinstance(default_nerve_provider(), NerveDetectionProvider)


class _StubDetector:
    """Minimal stub — proves the application seam accepts any engine."""

    name = "stub-nerve"
    input_kind = "scene"  # type: ignore[assignment]

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
        return NerveDetectionResult(
            provider=self.name, method="stub", performed_at=request.performed_at
        )


def test_stub_satisfies_port() -> None:
    assert isinstance(_StubDetector(), NerveDetectionProvider)


@pytest.mark.asyncio
async def test_deterministic_across_calls_and_instances() -> None:
    request = _request()
    first = await CanonicalMandibleNerveProvider().detect(request)
    second = await CanonicalMandibleNerveProvider().detect(request)
    assert first.model_dump() == second.model_dump()


# ---------------------------------------------------------------------------
# Canonical-mandible provider behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_left_and_right_pathways() -> None:
    result = await default_nerve_provider().detect(_request())
    assert [p.side for p in result.pathways] == ["left", "right"]
    left, right = result.pathways
    assert left.region == right.region == "mandibular_canal"
    assert left.source == right.source == "canonical_demo_model"
    # Mirrored about the midline (patient left = +x in the arch frame).
    assert [round(p.x, 6) for p in left.points] == [round(-p.x, 6) for p in right.points]
    assert [p.y for p in left.points] == [p.y for p in right.points]
    assert [p.z for p in left.points] == [p.z for p in right.points]
    # A plausible canal polyline, not a single segment.
    assert all(len(p.points) >= 4 for p in result.pathways)


@pytest.mark.asyncio
async def test_uncertain_without_patient_geometry() -> None:
    result = await default_nerve_provider().detect(_request(meshes=[]))
    assert all(p.status == "uncertain" for p in result.pathways)
    assert all(p.confidence == 0.6 for p in result.pathways)
    assert all(p.evidence.basis == "anatomical_model" for p in result.pathways)
    assert all(p.evidence.backing_documents == [] for p in result.pathways)
    assert "demo" in result.pathways[0].evidence.note


@pytest.mark.asyncio
async def test_detected_with_scan_backing_but_capped_confidence() -> None:
    mesh = _mesh()
    result = await default_nerve_provider().detect(_request(meshes=[mesh]))
    assert all(p.status == "detected" for p in result.pathways)
    # Even scan-backed, the pathway is canonical — never a patient canal:
    # confidence stays at 0.75, below the "high" band (0.8).
    assert all(p.confidence == 0.75 for p in result.pathways)
    assert all(p.confidence < CONFIDENCE_HIGH for p in result.pathways)
    assert all(mesh.document_id in p.evidence.backing_documents for p in result.pathways)


@pytest.mark.asyncio
async def test_proximity_gradient_and_bands() -> None:
    result = await default_nerve_provider().detect(_request())
    by_tooth = {p.tooth_number: p for p in result.proximities}
    # Every present lower tooth is listed…
    assert sorted(by_tooth) == sorted(LOWER)
    # …with the anatomical gradient the model encodes.
    for near in (37, 38, 47, 48):
        assert by_tooth[near].warning == "near", near
        assert by_tooth[near].distance_mm < PROXIMITY_NEAR_MM
    for watch in (34, 35, 36, 44, 45, 46):
        assert by_tooth[watch].warning == "watch", watch
        assert PROXIMITY_NEAR_MM <= by_tooth[watch].distance_mm < PROXIMITY_WATCH_MM
    for none in (31, 32, 33, 41, 42, 43):
        assert by_tooth[none].warning == "none", none
    # Distance increases monotonically from third molar to central incisor.
    right_side = [by_tooth[n].distance_mm for n in (48, 47, 46, 45, 44, 43, 42, 41)]
    assert right_side == sorted(right_side)
    # Left mirrors right exactly.
    for left_tooth, right_tooth in ((38, 48), (35, 45), (31, 41)):
        assert by_tooth[left_tooth].distance_mm == pytest.approx(by_tooth[right_tooth].distance_mm)
        assert by_tooth[left_tooth].side == "left"
        assert by_tooth[right_tooth].side == "right"
    # Closest-point indices reference real polyline vertices.
    for proximity in result.proximities:
        pathway = next(p for p in result.pathways if p.side == proximity.side)
        assert 0 <= proximity.closest_point_index < len(pathway.points)


@pytest.mark.asyncio
async def test_upper_and_missing_teeth_excluded() -> None:
    teeth = [Tooth3D(tooth_number=n, present=True, condition="healthy") for n in PERMANENT]
    for tooth in teeth:
        if tooth.tooth_number in (48, 11, 21):
            tooth.present = False
    result = await default_nerve_provider().detect(_request(teeth=teeth))
    listed = {p.tooth_number for p in result.proximities}
    assert 48 not in listed  # absent tooth → no proximity
    assert 11 not in listed and 21 not in listed  # upper teeth never relate to the canal
    assert 47 in listed


@pytest.mark.asyncio
async def test_empty_scene_still_emits_both_pathways() -> None:
    result = await default_nerve_provider().detect(_request(teeth=[]))
    assert len(result.pathways) == 2
    assert result.proximities == []


def test_scale_factor_documented_in_module() -> None:
    # The mm scale is the contract between the frame and the display;
    # it must stay a single documented constant (ADR 0022).
    assert NERVE_MM_PER_UNIT == 10.0
    assert PROXIMITY_MAX_MM == 15.0
