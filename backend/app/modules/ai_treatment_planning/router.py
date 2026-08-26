"""AI Treatment Planning API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.llm.base import LLMError
from app.core.schemas import ApiResponse
from app.database import get_db

from .contracts import AITreatmentPlanningResult, ReviewRequest
from .generator import PlanningGenerationError
from .service import AITreatmentPlanningService

router = APIRouter()


@router.post("/patients/{patient_id}", response_model=ApiResponse[AITreatmentPlanningResult])
async def generate_treatment_planning(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_treatment_planning.generate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AITreatmentPlanningResult]:
    try:
        result = await AITreatmentPlanningService.generate(
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
    except (LLMError, PlanningGenerationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI treatment planning provider failed validation",
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/latest",
    response_model=ApiResponse[AITreatmentPlanningResult],
)
async def get_latest_treatment_planning(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_treatment_planning.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AITreatmentPlanningResult]:
    try:
        result = await AITreatmentPlanningService.get_latest(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI treatment planning result not found",
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/history",
    response_model=ApiResponse[list[AITreatmentPlanningResult]],
)
async def get_treatment_planning_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_treatment_planning.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AITreatmentPlanningResult]]:
    return ApiResponse(
        data=await AITreatmentPlanningService.get_history(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    )


@router.post(
    "/results/{planning_id}/review",
    response_model=ApiResponse[AITreatmentPlanningResult],
)
async def review_treatment_planning(
    planning_id: UUID,
    payload: ReviewRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_treatment_planning.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AITreatmentPlanningResult]:
    try:
        result = await AITreatmentPlanningService.review(
            db,
            clinic_id=ctx.clinic_id,
            planning_id=planning_id,
            reviewer_id=ctx.user_id,
            reviewer_role=ctx.role,
            decision=payload.decision,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI treatment planning result not found",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dentist review is required",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)
