"""Treatment Simulation API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .contracts import SimulationRequest, TreatmentSimulationResult
from .service import TreatmentSimulationService
from .simulator import SimulationBuildError

router = APIRouter()


@router.post("/patients/{patient_id}", response_model=ApiResponse[TreatmentSimulationResult])
async def create_treatment_simulation(
    patient_id: UUID,
    payload: SimulationRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_simulation.generate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentSimulationResult]:
    try:
        result = await TreatmentSimulationService.generate(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            planning_id=payload.planning_id,
            option_id=payload.option_id,
            user_id=ctx.user_id,
        )
    except KeyError as exc:
        detail = "Accepted treatment planning result or patient not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Treatment Simulation requires an accepted dentist-reviewed treatment plan",
        ) from exc
    except (ValueError, SimulationBuildError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/latest",
    response_model=ApiResponse[TreatmentSimulationResult],
)
async def get_latest_treatment_simulation(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_simulation.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentSimulationResult]:
    try:
        result = await TreatmentSimulationService.get_latest(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Treatment Simulation result not found",
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/history",
    response_model=ApiResponse[list[TreatmentSimulationResult]],
)
async def get_treatment_simulation_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_simulation.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[TreatmentSimulationResult]]:
    return ApiResponse(
        data=await TreatmentSimulationService.get_history(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    )
