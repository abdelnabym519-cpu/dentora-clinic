"""Service-layer, router-mapping, module-isolation and Alembic-branch tests
for the Orthodontic Simulator.

Complements ``test_orthodontic_simulator.py`` (pure domain + monkeypatched
scenes): these tests run against **real seeded dental_3d fixtures** in the
test database and through the mounted ASGI router, proving the intentional
fail-closed behaviour end to end:

* an accepted millimetre alignment parses through the real
  ``DentalAlignmentService`` contract (``accepted_alignment=True``);
* capability still fails closed while no reviewed per-tooth geometry
  exists in the Dental3D scene (``translation_eligible=False``);
* the simulate endpoint maps ``SimulatorSafetyError`` to HTTP 409,
  unknown patients to 404 and missing permissions to 403;
* the module stays stateless and its isolated Alembic branch never
  traverses another module's revisions.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.core.plugins.alembic_paths import discover_version_locations
from app.modules.dental_3d.models import DentalAlignmentResult
from app.modules.orthodontic_simulator import OrthodonticSimulatorModule
from app.modules.orthodontic_simulator.service import (
    OrthodonticSimulatorService,
    SimulationRequest,
    SimulatorSafetyError,
)
from app.modules.patients.models import Patient

BACKEND_ROOT = Path(__file__).resolve().parents[3]

_DIGEST = "sha256:" + "b" * 64

# Rotation of +90° around Z plus a (1, 2, 3) translation — a valid SE(3)
# rigid transform (orthonormal rotation block, determinant +1).
_SE3_MATRIX = [
    [0.0, -1.0, 0.0, 1.0],
    [1.0, 0.0, 0.0, 2.0],
    [0.0, 0.0, 1.0, 3.0],
    [0.0, 0.0, 0.0, 1.0],
]

_ALIGNMENT_PROVENANCE = {
    "ios": {
        "identifier": "ios-scan-doc",
        "digest": _DIGEST,
        "document_ids": [],
        "original_unit": "mm",
        "normalized_unit": "mm",
    },
    "cbct": {
        "identifier": "cbct-series-doc",
        "digest": "sha256:" + "c" * 64,
        "document_ids": [],
        "original_unit": "mm",
        "normalized_unit": "mm",
    },
    "anatomy_model_id": "dental_segmentator",
    "anatomy_model_version": "1.0.0",
}

# Deterministic technical metrics required by the AlignmentResult contract
# for any non-failed registration row. None of these is a clinical threshold.
_ALIGNMENT_METRICS = {
    "initializer": "open3d_ransac",
    "source_point_count": 1000,
    "target_point_count": 1000,
    "feature_correspondence_count": 64,
    "inlier_correspondence_count": 50,
    "global_fitness": 0.9,
    "global_inlier_rmse_mm": 0.4,
    "icp_fitness": 0.95,
    "icp_inlier_rmse_mm": 0.2,
    "overlap_ratio": 0.85,
    "icp_iterations": 17,
    "icp_converged": True,
    "outlier_ratio": 0.05,
}


async def _seed_accepted_alignment(
    db: AsyncSession, clinic_id, patient_id
) -> DentalAlignmentResult:
    """Seed an accepted, reviewed IOS→CBCT registration result row."""
    row = DentalAlignmentResult(
        clinic_id=clinic_id,
        patient_id=patient_id,
        status="accepted",
        algorithm="open3d_ransac_icp",
        algorithm_version="dentora-open3d-rigid-v1",
        transform={"matrix": _SE3_MATRIX},
        source_frame={
            "id": "dicom_patient_cbct",
            "kind": "dicom_patient",
            "unit": "mm",
            "frame_of_reference_uid": "1.2.840.113619.1",
        },
        target_frame={"id": "ios_scan_mm", "kind": "ios_mesh", "unit": "mm"},
        provenance=_ALIGNMENT_PROVENANCE,
        metrics=_ALIGNMENT_METRICS,
        performed_at=datetime.now(UTC),
        reviewed_by=None,
        reviewed_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    return row


async def _receptionist_headers(db: AsyncSession, clinic_id) -> dict[str, str]:
    user = User(
        id=uuid4(),
        email=f"recep-{uuid4().hex[:8]}@test.clinic",
        password_hash=hash_password("TestPass1234"),
        first_name="Recep",
        last_name="Tionist",
    )
    db.add(user)
    await db.flush()
    db.add(ClinicMembership(id=uuid4(), user_id=user.id, clinic_id=clinic_id, role="receptionist"))
    await db.commit()
    token = create_access_token(user.id, token_version=user.token_version)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service layer against seeded dental_3d fixtures
# ---------------------------------------------------------------------------


async def test_capability_accepts_seeded_alignment_but_fails_closed(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    """The seeded accepted mm alignment is recognized, yet movement stays
    locked because no reviewed per-tooth geometry exists (whole-arch-only
    contract) and no tooth-local frame is available."""
    await _seed_accepted_alignment(db_session, test_clinic.id, test_patient.id)

    capability = await OrthodonticSimulatorService.capability(
        db_session, test_clinic.id, test_patient.id
    )

    assert capability.accepted_alignment is True
    assert capability.translation_eligible is False
    assert capability.rotation_eligible is False
    reason_codes = {reason.code for reason in capability.reasons}
    assert "no-real-mesh" in reason_codes
    assert "tooth-local-frame-unavailable" in reason_codes
    assert capability.clinical_prediction is False
    assert capability.treatment_approval is False


async def test_capability_without_alignment_reports_untrusted_frame(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    capability = await OrthodonticSimulatorService.capability(
        db_session, test_clinic.id, test_patient.id
    )

    assert capability.accepted_alignment is False
    assert capability.translation_eligible is False
    reason_codes = {reason.code for reason in capability.reasons}
    assert "no-real-mesh" in reason_codes


async def test_simulate_raises_safety_error_without_reviewed_geometry(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    await _seed_accepted_alignment(db_session, test_clinic.id, test_patient.id)

    request = SimulationRequest.model_validate(
        {
            "movements": [
                {
                    "tooth": {"value": "11", "system": "FDI"},
                    "translate_x_mm": 1.0,
                }
            ]
        }
    )
    try:
        await OrthodonticSimulatorService.simulate(
            db_session, test_clinic.id, test_patient.id, request
        )
    except SimulatorSafetyError:
        pass
    else:  # pragma: no cover - explicit failure message
        raise AssertionError("simulation must fail closed without reviewed per-tooth geometry")


# ---------------------------------------------------------------------------
# Router contract: envelope, 404 / 409 / 403 mapping
# ---------------------------------------------------------------------------


async def test_capability_endpoint_returns_fail_closed_capability(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    response = await client.get(
        f"/api/v1/orthodontic_simulator/patients/{test_patient.id}/capability",
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["patient_id"] == str(test_patient.id)
    assert payload["translation_eligible"] is False
    assert payload["clinical_prediction"] is False
    assert payload["treatment_approval"] is False
    assert isinstance(payload["reasons"], list) and payload["reasons"]


async def test_simulate_endpoint_maps_safety_error_to_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    """A valid request body that the geometry gate rejects maps the
    ``SimulatorSafetyError`` to HTTP 409 — never 500."""
    response = await client.post(
        f"/api/v1/orthodontic_simulator/patients/{test_patient.id}/simulate",
        headers=auth_headers,
        json={
            "movements": [
                {"tooth": {"value": "11", "system": "FDI"}, "translate_x_mm": 1.0},
            ]
        },
    )
    assert response.status_code == 409


async def test_unknown_patient_returns_404(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    response = await client.get(
        f"/api/v1/orthodontic_simulator/patients/{uuid4()}/capability",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_role_without_permission_gets_403(
    client: AsyncClient,
    db_session: AsyncSession,
    test_clinic: Clinic,
    test_patient: Patient,
) -> None:
    headers = await _receptionist_headers(db_session, test_clinic.id)
    response = await client.get(
        f"/api/v1/orthodontic_simulator/patients/{test_patient.id}/capability",
        headers=headers,
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Module isolation / statelessness + Alembic branch registration
# ---------------------------------------------------------------------------


def test_orthodontic_simulator_module_is_stateless_and_removable() -> None:
    manifest = OrthodonticSimulatorModule.manifest
    assert manifest["removable"] is True
    assert manifest["auto_install"] is False
    assert "dental_3d" in manifest["depends"]
    # Stateless: no SQLAlchemy models are exported for uninstall roundtrips.
    assert OrthodonticSimulatorModule.get_models(OrthodonticSimulatorModule) == []


def _script_directory() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("version_path_separator", "os")
    cfg.set_main_option(
        "version_locations",
        os.pathsep.join(
            discover_version_locations(
                BACKEND_ROOT / "alembic" / "versions",
                BACKEND_ROOT / "app" / "modules",
            )
        ),
    )
    return ScriptDirectory.from_config(cfg)


def test_ported_module_branches_are_registered_and_isolated() -> None:
    """``dental_3d`` and ``orthodontic_simulator`` Alembic branches are
    discovered, anchored at core ``0001``, and the simulator branch walk
    never enters another module's revision space."""
    script = _script_directory()

    ortho = script.get_revision("ortho_sim_0001")
    assert ortho.down_revision == "0001"
    assert "orthodontic_simulator" in (ortho.branch_labels or set())

    d3d_head = script.get_revision("d3d_0006")
    assert "dental_3d" in (d3d_head.branch_labels or set())
    assert script.get_revision("d3d_0001").down_revision == "0001"

    # Both ported branches are reachable heads.
    heads = set(script.get_heads())
    assert "ortho_sim_0001" in heads
    assert "d3d_0006" in heads

    # Uninstall/downgrade walk from the simulator head touches only its own
    # revision plus the shared core root — never another module's revisions.
    walked: list[str] = []
    for revision in script.walk_revisions("ortho_sim_0001"):
        walked.append(revision.revision)
        if revision.down_revision is None or revision.down_revision == "0001":
            break
    assert walked == ["ortho_sim_0001"]
