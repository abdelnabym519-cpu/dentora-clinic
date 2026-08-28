"""Orthodontic Simulator API: read capability, then deterministic simulation."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.patients.models import Patient

from .service import (
    OrthodonticSimulatorService,
    SimulationRequest,
    SimulationResponse,
    SimulatorCapability,
    SimulatorSafetyError,
)

router = APIRouter()


async def _ensure_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> None:
    stmt = select(Patient.id).where(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
        Patient.status != "archived",
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")


@router.get(
    "/patients/{patient_id}/capability",
    response_model=ApiResponse[SimulatorCapability],
)
async def get_capability(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_simulator.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SimulatorCapability]:
    """Return fail-closed patient geometry/frame eligibility without modifying Dental3D."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    capability = await OrthodonticSimulatorService.capability(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=capability)


@router.post(
    "/patients/{patient_id}/simulate",
    response_model=ApiResponse[SimulationResponse],
)
async def run_simulation(
    patient_id: UUID,
    data: SimulationRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("orthodontic_simulator.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[SimulationResponse]:
    """Compute a transient deterministic simulation; no source geometry is persisted or changed."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await OrthodonticSimulatorService.simulate(
            db, ctx.clinic_id, patient_id, data
        )
    except SimulatorSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)
