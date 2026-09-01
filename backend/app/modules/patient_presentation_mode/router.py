"""Patient Presentation Mode API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .contracts import PatientPresentation
from .service import PatientPresentationService, PresentationNotReadyError

router = APIRouter()


@router.get("/patients/{patient_id}", response_model=ApiResponse[PatientPresentation])
async def get_patient_presentation(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patient_presentation_mode.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PatientPresentation]:
    if ctx.role != "dentist":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dentist control is required for patient presentation",
        )
    try:
        result = await PatientPresentationService.get_current(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Presentation source not found",
        ) from exc
    except PresentationNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=result)
