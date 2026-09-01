from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.dental_3d.registration_service import DentalAlignmentService
from app.modules.dental_3d.service import DentalSceneService
from app.modules.orthodontic_simulator.domain import (
    Arch,
    BoundsMm,
    CoordinateFrame,
    FdiToothId,
    MovementCaps,
    SimulationPlan,
    Stage,
    ToothDelta,
    ToothGeometryRef,
    cumulative_poses,
    evaluate_geometry,
    proximity_findings,
    reproducibility_digest,
    simulate,
    stage_movements,
)
from app.modules.orthodontic_simulator.service import (
    AuthoredMovement,
    OrthodonticSimulatorService,
    SimulationRequest,
    SimulatorSafetyError,
)

DIGEST = "sha256:" + "a" * 64


def geometry(
    fdi: str = "11",
    *,
    scale: bool = True,
    trusted: bool = True,
    reviewed: bool = True,
    per_tooth: bool = True,
    local_frame: bool = False,
) -> ToothGeometryRef:
    return ToothGeometryRef(
        tooth=FdiToothId(value=fdi),
        document_id=f"doc-{fdi}",
        source_digest=DIGEST,
        frame=CoordinateFrame(
            id="ios-mm",
            scale_verified=scale,
            trusted=trusted,
        ),
        reviewed=reviewed,
        per_tooth=per_tooth,
        trusted_tooth_local_frame=local_frame,
    )


def delta(fdi: str = "11", **values: float) -> ToothDelta:
    return ToothDelta(
        tooth=FdiToothId(value=fdi),
        coordinate_frame="ios-mm",
        **values,
    )


def test_fdi_identity_and_invalid_inputs() -> None:
    assert FdiToothId(value="11").arch is Arch.MAXILLARY
    assert FdiToothId(value="36").arch is Arch.MANDIBULAR
    with pytest.raises(ValidationError):
        FdiToothId(value="99")
    with pytest.raises(ValidationError):
        delta(translate_x_mm=float("nan"))
    with pytest.raises(ValidationError):
        delta(translate_x_mm=21.0)


def test_staging_is_deterministic_and_does_not_mutate_authored_delta() -> None:
    authored = delta(translate_x_mm=0.50)
    stages = stage_movements((authored,), MovementCaps())

    assert [stage.index for stage in stages] == [0, 1]
    assert [stage.deltas[0].translate_x_mm for stage in stages] == [0.25, 0.25]
    assert authored.translate_x_mm == 0.50


def test_scale_frame_and_rotation_gates_fail_closed() -> None:
    unscaled = geometry(scale=False, trusted=False)
    codes = {finding.code for finding in evaluate_geometry(unscaled)}
    assert {"scale-unverified", "frame-untrusted", "rotation-frame-untrusted"} <= codes
    assert unscaled.translation_renderable is False
    assert unscaled.rotation_renderable is False

    translated = geometry(local_frame=False)
    assert translated.translation_renderable is True
    assert translated.rotation_renderable is False

    fully_trusted = geometry(local_frame=True)
    assert fully_trusted.translation_renderable is True
    assert fully_trusted.rotation_renderable is True


def test_coordinate_frames_cannot_be_mixed() -> None:
    plan = SimulationPlan(
        geometry=(geometry(),),
        stages=(Stage(index=0, deltas=(delta(translate_x_mm=0.1),)),),
    )
    pose = cumulative_poses(plan)[0]["11"]
    with pytest.raises(ValueError, match="different coordinate frames"):
        pose.apply(
            ToothDelta(
                tooth=FdiToothId(value="11"),
                coordinate_frame="other-frame",
                translate_x_mm=0.1,
            )
        )

    with pytest.raises(ValidationError, match="coordinate frame"):
        SimulationPlan(
            geometry=(geometry(),),
            stages=(
                Stage(
                    index=0,
                    deltas=(
                        ToothDelta(
                            tooth=FdiToothId(value="11"),
                            coordinate_frame="other-frame",
                            translate_x_mm=0.1,
                        ),
                    ),
                ),
            ),
        )


def test_source_models_are_immutable_and_result_is_non_clinical() -> None:
    source = geometry()
    plan = SimulationPlan(
        geometry=(source,),
        stages=stage_movements((delta(translate_y_mm=0.5),), MovementCaps()),
    )
    result = simulate(plan)

    assert result.mutates_source_geometry is False
    assert result.synthetic_geometry is False
    assert result.clinical_prediction is False
    assert result.treatment_approval is False
    assert source.frame.id == "ios-mm"
    with pytest.raises(ValidationError):
        source.frame.id = "mutated"  # type: ignore[misc]


def test_reproducibility_digest_is_stable_and_input_sensitive() -> None:
    plan = SimulationPlan(
        geometry=(geometry(),),
        stages=stage_movements((delta(translate_x_mm=0.25),), MovementCaps()),
    )
    assert reproducibility_digest(plan) == reproducibility_digest(plan.model_copy(deep=True))

    changed = SimulationPlan(
        geometry=(geometry(),),
        stages=stage_movements((delta(translate_x_mm=0.30),), MovementCaps()),
    )
    assert reproducibility_digest(changed) != reproducibility_digest(plan)


def test_static_proximity_is_deterministic_engineering_warning_only() -> None:
    left = geometry("11").model_copy(
        update={"bounds_mm": BoundsMm(min_xyz=(0, 0, 0), max_xyz=(1, 1, 1))}
    )
    right = geometry("21").model_copy(
        update={"bounds_mm": BoundsMm(min_xyz=(1.02, 0, 0), max_xyz=(2, 1, 1))}
    )
    findings = proximity_findings((left, right), minimum_gap_mm=0.05)
    assert len(findings) == 1
    assert findings[0].code == "proximity-warning"
    assert findings[0].severity == "notice"


def test_plan_rejects_unmapped_teeth_and_non_contiguous_stages() -> None:
    with pytest.raises(ValidationError, match="unmapped tooth"):
        SimulationPlan(
            geometry=(geometry("11"),),
            stages=(Stage(index=0, deltas=(delta("21", translate_x_mm=0.1),)),),
        )

    with pytest.raises(ValidationError, match="contiguous"):
        SimulationPlan(
            geometry=(geometry(),),
            stages=(Stage(index=1, deltas=(delta(translate_x_mm=0.1),)),),
        )


@pytest.mark.asyncio
async def test_current_whole_arch_dental3d_contract_fails_closed(monkeypatch) -> None:
    scene = SimpleNamespace(
        meshes=[SimpleNamespace(document_id=uuid4())],
        teeth=[
            SimpleNamespace(
                tooth_number=11,
                present=True,
                mesh=SimpleNamespace(source="synthetic", document_id=None, format="procedural"),
            )
        ],
        segmentation=SimpleNamespace(review_status="accepted"),
    )
    monkeypatch.setattr(DentalSceneService, "get_for_patient", AsyncMock(return_value=scene))
    monkeypatch.setattr(DentalAlignmentService, "latest_alignment", AsyncMock(return_value=None))

    patient_id = uuid4()
    capability = await OrthodonticSimulatorService.capability(
        SimpleNamespace(),
        uuid4(),
        patient_id,  # type: ignore[arg-type]
    )

    assert capability.patient_id == patient_id
    assert capability.whole_arch_mesh_count == 1
    assert capability.per_tooth_mesh_count == 0
    assert capability.translation_eligible is False
    assert capability.rotation_eligible is False
    assert "whole-arch-only" in {reason.code for reason in capability.reasons}


@pytest.mark.asyncio
async def test_simulation_cannot_bypass_server_owned_geometry_gate(monkeypatch) -> None:
    scene = SimpleNamespace(
        meshes=[SimpleNamespace(document_id=uuid4())],
        teeth=[],
        segmentation=SimpleNamespace(review_status=None),
    )
    monkeypatch.setattr(DentalSceneService, "get_for_patient", AsyncMock(return_value=scene))
    monkeypatch.setattr(DentalAlignmentService, "latest_alignment", AsyncMock(return_value=None))

    request = SimulationRequest(
        movements=(AuthoredMovement(tooth=FdiToothId(value="11"), translate_x_mm=0.1),)
    )
    with pytest.raises(SimulatorSafetyError, match="reviewed per-tooth geometry"):
        await OrthodonticSimulatorService.simulate(
            SimpleNamespace(),
            uuid4(),
            uuid4(),
            request,  # type: ignore[arg-type]
        )
