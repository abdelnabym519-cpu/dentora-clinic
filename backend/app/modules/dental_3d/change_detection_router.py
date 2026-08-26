"""HTTP contract for longitudinal Change Detection."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .change_detection import (
    ChangeDetectionRequest,
    ChangeDetectionResponse,
    ChangeDetectionService,
)

router = APIRouter()


@router.post(
    "/cases/{patient_id}/compare",
    response_model=ApiResponse[ChangeDetectionResponse],
)
async def compare_case_timepoints(
    patient_id: UUID,
    data: ChangeDetectionRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ChangeDetectionResponse]:
    """Compare two immutable patient snapshots after compatible registration."""

    try:
        result = await ChangeDetectionService.compare(
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
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Case Intelligence snapshot provider unavailable",
        ) from exc
    return ApiResponse(data=result)
