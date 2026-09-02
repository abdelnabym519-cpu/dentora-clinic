"""API + isolation tests for the dental_3d module.

Exercises the mounted router at ``/api/v1/dental_3d/`` through the
ASGI client: response envelope, round-trip persistence, RBAC gates,
clinic isolation and the agent-tool registration.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.core.auth.service import create_access_token, hash_password
from app.core.plugins.loader import discover_modules
from app.modules.dental_3d.schemas import DentalSceneUpdate, Tooth3D
from app.modules.patients.models import Patient


def _scene_url(patient_id) -> str:
    return f"/api/v1/dental_3d/patients/{patient_id}/scene"


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


@pytest.mark.asyncio
async def test_get_returns_default_synthetic_scene(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    response = await client.get(_scene_url(test_patient.id), headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["persisted"] is False
    assert payload["generator"] == "synthetic"
    assert payload["segmentation"]["status"] == "not_available"
    assert len(payload["teeth"]) == 32


@pytest.mark.asyncio
async def test_put_persists_view_state_and_get_round_trips(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    update = DentalSceneUpdate(teeth=[Tooth3D(tooth_number=16, visible=False, color="#EF4444")])
    response = await client.put(
        _scene_url(test_patient.id), headers=auth_headers, json=update.model_dump(mode="json")
    )
    assert response.status_code == 200
    assert response.json()["data"]["persisted"] is True

    response = await client.get(_scene_url(test_patient.id), headers=auth_headers)
    assert response.status_code == 200
    by_number = {t["tooth_number"]: t for t in response.json()["data"]["teeth"]}
    assert by_number[16]["visible"] is False
    assert by_number[16]["color"] == "#EF4444"
    assert by_number[11]["visible"] is True


@pytest.mark.asyncio
async def test_unknown_patient_returns_404(
    client: AsyncClient, auth_headers: dict[str, str], test_clinic: Clinic
) -> None:
    # test_clinic gives the authed user a membership (context resolves);
    # the random patient id itself must 404.
    response = await client.get(_scene_url(uuid4()), headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cross_clinic_patient_returns_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_clinic: Clinic,
) -> None:
    other = Clinic(id=uuid4(), name="Other", tax_id="B00000000", address={}, settings={})
    db_session.add(other)
    await db_session.flush()
    stranger = Patient(
        id=uuid4(),
        clinic_id=other.id,
        first_name="Other",
        last_name="Clinic",
        email="stranger@other.clinic",
        phone="+34600000000",
    )
    db_session.add(stranger)
    await db_session.commit()

    # test user is admin of test_clinic only → the other clinic's patient
    # must be invisible (404, not a data leak).
    response = await client.get(_scene_url(stranger.id), headers=auth_headers)
    assert response.status_code == 404
    response = await client.put(
        _scene_url(stranger.id),
        headers=auth_headers,
        json=DentalSceneUpdate(teeth=[]).model_dump(mode="json"),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_receptionist_is_forbidden(
    client: AsyncClient, db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient
) -> None:
    headers = await _receptionist_headers(db_session, test_clinic.id)
    response = await client.get(_scene_url(test_patient.id), headers=headers)
    assert response.status_code == 403
    response = await client.put(
        _scene_url(test_patient.id),
        headers=headers,
        json=DentalSceneUpdate(teeth=[]).model_dump(mode="json"),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_tooth_number_returns_422(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    response = await client.put(
        _scene_url(test_patient.id),
        headers=auth_headers,
        json={"teeth": [{"tooth_number": 99}]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_completed_segmentation_rejected_422(
    client: AsyncClient, auth_headers: dict[str, str], test_patient: Patient
) -> None:
    # Schema-level guard proven in the contracts test; here the same guard
    # must hold through the HTTP boundary.
    response = await client.put(
        _scene_url(test_patient.id),
        headers=auth_headers,
        json={"teeth": [], "segmentation": {"status": "completed", "teeth_found": 32}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_authentication_required(client: AsyncClient, test_patient: Patient) -> None:
    response = await client.get(_scene_url(test_patient.id))
    assert response.status_code in (401, 403)


class TestModuleRegistration:
    def test_module_discovered_with_expected_manifest(self) -> None:
        modules = {m.name: m for m in discover_modules()}
        assert "dental_3d" in modules
        module = modules["dental_3d"]
        manifest = module.get_manifest()
        assert list(manifest.depends) == ["patients", "odontogram", "media"]
        assert manifest.removable is True
        assert manifest.installable is True
        assert manifest.auto_install is False
        assert sorted(module.get_permissions()) == ["read", "write"]

    def test_agent_tool_registered(self) -> None:
        from app.core.agents.tools.registry import tool_registry

        assert "dental_3d.get_patient_scene" in tool_registry.list()
        tool = tool_registry.get("dental_3d.get_patient_scene")
        assert tool is not None
        assert tool.category.value == "read"
        assert tool.permissions == ["dental_3d.read"]

    @pytest.mark.asyncio
    async def test_agent_tool_returns_scene_for_own_clinic(
        self, db_session: AsyncSession, test_patient: Patient
    ) -> None:
        from types import SimpleNamespace

        from app.core.agents.tools.registry import tool_registry
        from app.modules.dental_3d.tools import GetPatientSceneArgs

        tool = tool_registry.get("dental_3d.get_patient_scene")
        ctx = SimpleNamespace(db=db_session, clinic_id=test_patient.clinic_id)
        result = await tool.handler(ctx, GetPatientSceneArgs(patient_id=test_patient.id))
        # Native values (UUID) — the registry chokepoint jsonifies later.
        assert result["patient_id"] == test_patient.id
        assert len(result["teeth"]) == 32

        stranger = SimpleNamespace(db=db_session, clinic_id=uuid4())
        result = await tool.handler(stranger, GetPatientSceneArgs(patient_id=test_patient.id))
        assert result == {"error": "not_found"}
