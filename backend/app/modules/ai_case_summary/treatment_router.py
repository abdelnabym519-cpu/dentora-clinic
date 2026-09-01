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

from .treatment_contracts import AITreatmentPlan, TreatmentReviewRequest
from .treatment_generator import TreatmentGenerationError
from .treatment_service import AITreatmentPlanningService

router = APIRouter()


@router.post(
    "/patients/{patient_id}/treatment-planning",
    response_model=ApiResponse[AITreatmentPlan],
)
async def generate_treatment_plan(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_case_summary.generate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AITreatmentPlan]:
    try:
        result = await AITreatmentPlanningService.generate(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (LLMError, TreatmentGenerationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/treatment-planning/latest",
    response_model=ApiResponse[AITreatmentPlan],
)
async def get_latest_treatment_plan(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_case_summary.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AITreatmentPlan]:
    try:
        result = await AITreatmentPlanningService.get_latest(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI treatment plan not found",
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/treatment-planning/history",
    response_model=ApiResponse[list[AITreatmentPlan]],
)
async def get_treatment_plan_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_case_summary.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AITreatmentPlan]]:
    result = await AITreatmentPlanningService.get_history(
        db,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
    )
    return ApiResponse(data=result)


@router.post(
    "/treatment-planning/{plan_id}/review",
    response_model=ApiResponse[AITreatmentPlan],
)
async def review_treatment_plan(
    plan_id: UUID,
    payload: TreatmentReviewRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_case_summary.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AITreatmentPlan]:
    try:
        result = await AITreatmentPlanningService.review(
            db,
            clinic_id=ctx.clinic_id,
            plan_id=plan_id,
            reviewer_id=ctx.user_id,
            reviewer_role=ctx.role,
            decision=payload.decision,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI treatment plan not found",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dentist review is required",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)
