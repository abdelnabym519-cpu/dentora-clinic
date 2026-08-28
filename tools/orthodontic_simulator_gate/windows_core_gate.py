from __future__ import annotations

import importlib.metadata as metadata
import os
import platform
import socket
import sys

FORBIDDEN_DISTRIBUTIONS = (
    "openai",
    "onnxruntime",
    "onnxruntime-gpu",
    "torch",
    "tensorflow",
    "tensorflow-intel",
)
FORBIDDEN_ENV = (
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "CUDA_VISIBLE_DEVICES",
)


def _deny_network(*_args, **_kwargs):
    raise AssertionError("network access attempted during offline core gate")


def _assert_forbidden_runtime_absent() -> None:
    installed = {dist.metadata["Name"].lower() for dist in metadata.distributions() if dist.metadata.get("Name")}
    forbidden = [name for name in FORBIDDEN_DISTRIBUTIONS if name.lower() in installed]
    assert not forbidden, f"forbidden runtime distributions installed: {forbidden}"
    leaked_env = [name for name in FORBIDDEN_ENV if os.environ.get(name)]
    assert not leaked_env, f"forbidden runtime configuration present: {leaked_env}"


def main() -> int:
    assert platform.system() == "Windows", platform.platform()
    assert platform.architecture()[0] == "64bit", platform.architecture()
    assert sys.version_info[:2] in {(3, 11), (3, 12)}, sys.version
    _assert_forbidden_runtime_absent()

    # The core must execute with network disabled. Installation happens before this
    # script; all domain/planning operations below are required to be local-only.
    socket.create_connection = _deny_network  # type: ignore[assignment]
    socket.socket.connect = _deny_network  # type: ignore[assignment]

    from pydantic import ValidationError

    from orthoplan.evaluation.rules.movement_caps import evaluate_movement_caps
    from orthoplan.model.assets import (
        BoundingBox,
        MeshAsset,
        MeshUnits,
        UploadedScan,
        bounding_box_sanity,
    )
    from orthoplan.model.plan import Stage, ToothDelta, TreatmentPlan
    from orthoplan.model.identity import Arch, ToothId
    from orthoplan.planning.optimizer import optimize_staging
    from orthoplan.planning.transforms import ToothPose

    # FDI identity and invalid input rejection.
    tooth_11 = ToothId(value="11")
    assert tooth_11.arch == Arch.MAXILLARY
    assert ToothId(value="36").arch == Arch.MANDIBULAR
    try:
        ToothId(value="99")
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid FDI identity was accepted")

    # Scale must fail closed when STL units are unverified.
    unknown_asset = MeshAsset(
        id="scan-unverified",
        format="stl",
        vertex_count=100,
        face_count=200,
        bounds=BoundingBox(min_xyz=(0.0, 0.0, 0.0), max_xyz=(60.0, 40.0, 30.0)),
    )
    unverified_plan = TreatmentPlan(
        id="unverified-scale",
        scans=[UploadedScan(asset=unknown_asset, arch="maxillary")],
    )
    assert not unverified_plan.scale_confirmed
    assert "unverified" in (bounding_box_sanity(unknown_asset) or "")

    mm_asset = unknown_asset.model_copy(update={"id": "scan-mm", "units": MeshUnits.MM})
    verified_plan = TreatmentPlan(
        id="verified-scale",
        scans=[UploadedScan(asset=mm_asset, arch="maxillary")],
    )
    assert verified_plan.scale_confirmed
    assert bounding_box_sanity(mm_asset) is None

    # Deterministic movement checks and cap-respecting staging.
    authored = ToothDelta(tooth=tooth_11, translate_x_mm=0.50, source="manual")
    authored_plan = TreatmentPlan(id="staging", stages=[Stage(index=0, deltas=[authored])])
    findings = evaluate_movement_caps(authored_plan)
    assert any(item.code == "movement-cap-exceeded" for item in findings)

    staged = optimize_staging(authored_plan)
    assert len(staged.plan.stages) == 2
    assert [s.index for s in staged.plan.stages] == [0, 1]
    assert all(len(s.deltas) == 1 for s in staged.plan.stages)
    assert all(abs(s.deltas[0].translate_x_mm - 0.25) < 1e-12 for s in staged.plan.stages)
    assert authored_plan.stages[0].deltas[0].translate_x_mm == 0.50, "source plan mutated"

    # Deterministic cumulative transforms; scan-local rotations must stay non-renderable.
    pose = ToothPose.from_delta(staged.plan.stages[0].deltas[0], rotation_renderable=False)
    pose2 = pose.apply_delta(staged.plan.stages[1].deltas[0])
    assert abs(pose2.translate_x_mm - 0.50) < 1e-12
    assert pose2.rotation_renderable is False

    try:
        pose.apply_delta(
            ToothDelta(tooth=tooth_11, translate_x_mm=0.1, coordinate_frame="different-frame")
        )
    except ValueError as exc:
        assert "different coordinate frames" in str(exc)
    else:
        raise AssertionError("cross-coordinate-frame transform was accepted")

    _assert_forbidden_runtime_absent()
    assert not any(name in sys.modules for name in ("openai", "onnxruntime", "torch", "tensorflow"))

    print("ORTHODONTIC_SIMULATOR_STANDALONE_WINDOWS_GATE=PASS")
    print(f"platform={platform.platform()}")
    print(f"python={platform.python_version()}")
    print("architecture=64bit")
    print("network=blocked_during_core_execution")
    print("api=none cloud=none openai=absent onnx=absent cuda=absent model_downloads=none")
    print("checks=fdi,invalid-input,scale,staging,movement-caps,transforms,coordinate-frame,immutability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
