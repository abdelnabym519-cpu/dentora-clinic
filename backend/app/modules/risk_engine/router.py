"""Risk Engine API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .contracts import ReviewRequest, RiskResult
from .service import RiskEngineService

router = APIRouter()


@router.post("/patients/{patient_id}", response_model=ApiResponse[RiskResult])
async def generate_risk_result(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("risk_engine.generate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RiskResult]:
    try:
        result = await RiskEngineService.generate(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        ) from exc
    return ApiResponse(data=result)


@router.get("/patients/{patient_id}/latest", response_model=ApiResponse[RiskResult])
async def get_latest_risk_result(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("risk_engine.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RiskResult]:
    try:
        result = await RiskEngineService.get_latest(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Risk result not found",
        ) from exc
    return ApiResponse(data=result)


@router.get("/patients/{patient_id}/history", response_model=ApiResponse[list[RiskResult]])
async def get_risk_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("risk_engine.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[RiskResult]]:
    return ApiResponse(
        data=await RiskEngineService.get_history(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    )


@router.post("/results/{result_id}/review", response_model=ApiResponse[RiskResult])
async def review_risk_result(
    result_id: UUID,
    payload: ReviewRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("risk_engine.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RiskResult]:
    try:
        result = await RiskEngineService.review(
            db,
            clinic_id=ctx.clinic_id,
            result_id=result_id,
            reviewer_id=ctx.user_id,
            reviewer_role=ctx.role,
            decision=payload.decision,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Risk result not found",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dentist review is required",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)
