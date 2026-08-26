"""Agent tools for the dental_3d module.

One READ wrapper over :class:`DentalSceneService` — the smallest
agent-addressable surface that makes 3D scene data reachable from the
copilot. No business logic lives here; the handler filters by
``ctx.clinic_id`` exactly like the HTTP route (repo tool convention:
plain dict results, ``{"error": ...}`` for misses).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.core.agents import AgentContext, Tool, ToolCategory

from .service import DentalSceneService


class GetPatientSceneArgs(BaseModel):
    patient_id: UUID = Field(description="Patient whose dental 3D scene to fetch.")


async def _get_patient_scene(ctx: AgentContext, params: GetPatientSceneArgs) -> dict:
    from sqlalchemy import select

    from app.modules.patients.models import Patient

    stmt = select(Patient).where(
        Patient.id == params.patient_id,
        Patient.clinic_id == ctx.clinic_id,
        Patient.status != "archived",
    )
    if (await ctx.db.execute(stmt)).scalar_one_or_none() is None:
        return {"error": "not_found"}

    scene = await DentalSceneService.get_for_patient(ctx.db, ctx.clinic_id, params.patient_id)
    return scene.model_dump()


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="get_patient_scene",
            description=(
                "Fetch a patient's dental 3D scene: per-tooth FDI numbers, "
                "presence, condition, mesh descriptors (synthetic teeth plus "
                "any real scan mesh references). Read-only."
            ),
            parameters=GetPatientSceneArgs,
            handler=_get_patient_scene,
            permissions=["dental_3d.read"],
            category=ToolCategory.READ,
        ),
    ]
