"""AI Case Summary API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.llm.base import LLMError
from app.core.schemas import ApiResponse
from app.database import get_db

from .contracts import AICaseSummary, ReviewRequest
from .generator import SummaryGenerationError
from .service import AICaseSummaryService

router = APIRouter()


@router.post("/patients/{patient_id}", response_model=ApiResponse[AICaseSummary])
async def generate_case_summary(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_case_summary.generate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AICaseSummary]:
    try:
        result = await AICaseSummaryService.generate(
            db, clinic_id=ctx.clinic_id, patient_id=patient_id, user_id=ctx.user_id
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
        ) from exc
    except (LLMError, SummaryGenerationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI summary provider failed validation",
        ) from exc
    return ApiResponse(data=result)


@router.get("/patients/{patient_id}/latest", response_model=ApiResponse[AICaseSummary])
async def get_latest_case_summary(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_case_summary.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AICaseSummary]:
    try:
        result = await AICaseSummaryService.get_latest(
            db, clinic_id=ctx.clinic_id, patient_id=patient_id
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found"
        ) from exc
    return ApiResponse(data=result)


@router.post("/summaries/{summary_id}/review", response_model=ApiResponse[AICaseSummary])
async def review_case_summary(
    summary_id: UUID,
    payload: ReviewRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_case_summary.review"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AICaseSummary]:
    try:
        result = await AICaseSummaryService.review(
            db,
            clinic_id=ctx.clinic_id,
            summary_id=summary_id,
            reviewer_id=ctx.user_id,
            reviewer_role=ctx.role,
            decision=payload.decision,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found"
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dentist review is required",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApiResponse(data=result)
