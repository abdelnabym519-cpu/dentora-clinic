"""Read-only Case Intelligence evidence/report API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.dental_3d.change_detection import (
    ChangeDetectionRequest,
    ChangeDetectionResponse,
)

from .contracts import CaseSnapshot
from .service import CaseIntelligenceService

router = APIRouter()


@router.get(
    "/patients/{patient_id}",
    response_model=ApiResponse[CaseSnapshot],
)
async def get_case_intelligence(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("case_intelligence.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    version: Annotated[int | None, Query(ge=1)] = None,
) -> ApiResponse[CaseSnapshot]:
    """Return the server-built unified case snapshot; no client snapshot is accepted."""

    try:
        if version is not None:
            result = await CaseIntelligenceService.get_version(
                db,
                clinic_id=ctx.clinic_id,
                patient_id=patient_id,
                version=version,
            )
        else:
            result = await CaseIntelligenceService.get_current(
                db,
                clinic_id=ctx.clinic_id,
                patient_id=patient_id,
                user_id=ctx.user_id,
            )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient or Case Intelligence snapshot not found",
        ) from exc
    return ApiResponse(data=result)


@router.post(
    "/cases/{patient_id}/compare",
    response_model=ApiResponse[ChangeDetectionResponse],
)
async def compare_case_timepoints(
    patient_id: UUID,
    data: ChangeDetectionRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("case_intelligence.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ChangeDetectionResponse]:
    """Compare two immutable patient snapshots after compatible registration."""

    try:
        result = await CaseIntelligenceService.compare_versions(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            baseline_version=data.baseline_version,
            followup_version=data.followup_version,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case Intelligence snapshot not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=result)
