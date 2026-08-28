"""AI Second Review API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .contracts import AISecondReviewRequest, AISecondReviewResult, DentistReviewRequest
from .generator import SecondReviewGenerationError
from .service import AISecondReviewService, SecondReviewSafetyError

router = APIRouter()


@router.post("/patients/{patient_id}", response_model=ApiResponse[AISecondReviewResult])
async def create_ai_second_review(
    patient_id: UUID,
    payload: AISecondReviewRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_second_review.generate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AISecondReviewResult]:
    try:
        result = await AISecondReviewService.generate(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            simulation_id=payload.simulation_id,
            user_id=ctx.user_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reviewed planning/simulation chain or patient not found",
        ) from exc
    except (SecondReviewSafetyError, SecondReviewGenerationError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/latest",
    response_model=ApiResponse[AISecondReviewResult],
)
async def get_latest_ai_second_review(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_second_review.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AISecondReviewResult]:
    try:
        result = await AISecondReviewService.get_latest(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI Second Review result not found",
        ) from exc
    return ApiResponse(data=result)


@router.get(
    "/patients/{patient_id}/history",
    response_model=ApiResponse[list[AISecondReviewResult]],
)
async def get_ai_second_review_history(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_second_review.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AISecondReviewResult]]:
    return ApiResponse(
        data=await AISecondReviewService.get_history(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    )


@router.post(
    "/results/{review_id}/review",
    response_model=ApiResponse[AISecondReviewResult],
)
async def mark_ai_second_review_reviewed(
    review_id: UUID,
    payload: DentistReviewRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_second_review.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AISecondReviewResult]:
    del payload
    try:
        result = await AISecondReviewService.mark_reviewed(
            db,
            clinic_id=ctx.clinic_id,
            review_id=review_id,
            reviewer_id=ctx.user_id,
            reviewer_role=ctx.role,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dentist review is required",
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI Second Review result not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)
