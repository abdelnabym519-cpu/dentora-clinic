"""Engineering geometry tests for deterministic implant planning."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.implant_planning import (
    ImplantCatalogEntry,
    PlanningCriterion,
    PlanningPolicy,
    ProstheticTargetCreate,
    ProstheticTargetResponse,
    UnitVector3D,
    assess_candidate,
    candidate_from_target,
    nerve_surface_distance_mm,
    parametric_implant_mesh,
    platform_point,
    prosthetic_measurements,
    rank_candidates,
)
from app.modules.dental_3d.registration import Point3D

FRAME = "2.25.123456789"
ALIGNMENT_ID = uuid4()
PATIENT_ID = uuid4()
TARGET_ID = uuid4()


def target() -> ProstheticTargetResponse:
    return ProstheticTargetResponse(
        id=TARGET_ID,
        patient_id=PATIENT_ID,
        alignment_id=ALIGNMENT_ID,
        platform_center=Point3D(x=10, y=20, z=30),
        axis=UnitVector3D(x=0, y=0, z=1),
        frame_of_reference_uid=FRAME,
        source_type="dentist_defined",
        source_reference_space="dicom_patient",
        source_frame_of_reference_uid=FRAME,
        source_method="explicit_dentist_entry",
        source_identifier="dentist-entry:fixture",
        review_status="accepted",
    )


def entry(identifier: str = "fixture-4x10", *, diameter: float = 4, length: float = 10):
    return ImplantCatalogEntry(
        id=identifier,
        label=identifier,
        diameter_mm=diameter,
        length_mm=length,
        dimension_source="fixture-explicit-dimensions",
    )


def test_axis_must_be_normalized() -> None:
    with pytest.raises(ValidationError):
        UnitVector3D(x=0, y=0, z=2)


def test_real_prosthetic_source_requires_provenance() -> None:
    with pytest.raises(ValidationError):
        ProstheticTargetCreate(
            alignment_id=ALIGNMENT_ID,
            platform_center=Point3D(x=0, y=0, z=0),
            axis=UnitVector3D(x=0, y=0, z=1),
            frame_of_reference_uid=FRAME,
            source_type="registered_ios",
            source_reference_space="ios_mesh",
            source_method="registered_scan",
            source_identifier="scan",
        )


def test_dicomp_patient_source_cannot_claim_another_frame() -> None:
    with pytest.raises(ValidationError):
        ProstheticTargetCreate(
            alignment_id=ALIGNMENT_ID,
            platform_center=Point3D(x=0, y=0, z=0),
            axis=UnitVector3D(x=0, y=0, z=1),
            frame_of_reference_uid=FRAME,
            source_type="dentist_defined",
            source_reference_space="dicom_patient",
            source_frame_of_reference_uid="2.25.999",
            source_method="explicit_dentist_entry",
            source_identifier="dentist-entry",
        )


def test_candidate_construction_preserves_target_platform_and_axis() -> None:
    candidate = candidate_from_target(target(), entry())
    assert candidate.center == Point3D(x=10, y=20, z=35)
    assert candidate.axis == UnitVector3D(x=0, y=0, z=1)
    assert platform_point(candidate) == target().platform_center

    offset, angle = prosthetic_measurements(candidate, target())
    assert offset.status == "AVAILABLE"
    assert offset.value == pytest.approx(0.0, abs=1e-9)
    assert angle.value == pytest.approx(0.0, abs=1e-9)


def test_parametric_mesh_uses_explicit_dimensions() -> None:
    candidate = candidate_from_target(target(), entry(diameter=4, length=10))
    mesh = parametric_implant_mesh(candidate, sections=24)
    assert mesh.is_empty is False
    assert sorted(mesh.extents.tolist()) == pytest.approx([4.0, 4.0, 10.0], abs=1e-6)


def test_nerve_distance_is_surface_to_centerline_not_canal_wall() -> None:
    candidate = candidate_from_target(
        ProstheticTargetResponse(
            **target().model_dump(exclude={"platform_center"}),
            platform_center=Point3D(x=0, y=0, z=-5),
        ),
        entry(diameter=4, length=10),
    )
    check, intersects = nerve_surface_distance_mm(
        candidate,
        [[Point3D(x=-10, y=5, z=0), Point3D(x=10, y=5, z=0)]],
    )
    assert check.status == "AVAILABLE"
    assert check.value == pytest.approx(3.0, abs=1e-6)
    assert check.semantics == "implant_surface_to_mandibular_canal_centerline"
    assert intersects is False


def test_tangent_or_intersection_reports_geometric_zero_only() -> None:
    candidate = candidate_from_target(
        ProstheticTargetResponse(
            **target().model_dump(exclude={"platform_center"}),
            platform_center=Point3D(x=0, y=0, z=-5),
        ),
        entry(diameter=4, length=10),
    )
    check, intersects = nerve_surface_distance_mm(
        candidate,
        [[Point3D(x=-10, y=2, z=0), Point3D(x=10, y=2, z=0)]],
    )
    assert check.value == pytest.approx(0.0, abs=1e-7)
    assert intersects is True


def test_missing_nerve_and_bone_stay_explicitly_unavailable() -> None:
    candidate = candidate_from_target(target(), entry())
    assessment = assess_candidate(candidate, target=target(), nerve_pathways=[])
    assert assessment.nerve_surface_to_centerline_mm.status == "UNAVAILABLE"
    assert assessment.nerve_surface_to_centerline_mm.value is None
    assert assessment.bone_axis_span_mm.status == "UNAVAILABLE"
    assert assessment.bone_width_1_mm.status == "UNAVAILABLE"
    assert assessment.bone_width_2_mm.status == "UNAVAILABLE"
    assert assessment.bone_contained_fraction.status == "UNAVAILABLE"
    assert assessment.bone_contained_volume_mm3.status == "UNAVAILABLE"
    assert assessment.clinical_threshold_status == "NO_CLINICAL_THRESHOLD_DEFINED"


def test_ranking_uses_only_caller_supplied_policy_and_is_reproducible() -> None:
    first = candidate_from_target(target(), entry("a", diameter=4.0, length=10.0))
    second = candidate_from_target(target(), entry("b", diameter=3.5, length=12.0))
    assessed = [
        (first, assess_candidate(first, target=target(), nerve_pathways=[])),
        (second, assess_candidate(second, target=target(), nerve_pathways=[])),
    ]
    policy = PlanningPolicy(
        criteria=[
            PlanningCriterion(name="diameter_mm", direction="asc"),
            PlanningCriterion(name="length_mm", direction="asc"),
        ]
    )
    once = rank_candidates(assessed, policy)
    twice = rank_candidates(list(reversed(assessed)), policy)
    assert [item[0].catalog_entry_id for item in once] == ["b", "a"]
    assert [item[0].catalog_entry_id for item in twice] == ["b", "a"]
