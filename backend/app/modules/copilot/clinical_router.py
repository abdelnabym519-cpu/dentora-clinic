"""Clinical Copilot API — advisory, dentist-controlled, no canonical writes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .clinical_contracts import ClinicalCopilotRequest, ClinicalCopilotResult
from .clinical_generator import ClinicalCopilotGenerationError
from .clinical_service import ClinicalCopilotService, ClinicalCopilotUnavailable

router = APIRouter()


@router.post(
    "/patients/{patient_id}/advice",
    response_model=ApiResponse[ClinicalCopilotResult],
)
async def generate_clinical_copilot_advice(
    patient_id: UUID,
    payload: ClinicalCopilotRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("copilot.chat"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicalCopilotResult]:
    try:
        result = await ClinicalCopilotService.generate(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            user_role=ctx.role,
            focus=payload.focus,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinical Copilot is dentist-controlled",
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        ) from exc
    except ClinicalCopilotUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "clinical_copilot_unavailable", "reasons": list(exc.reasons)},
        ) from exc
    except ClinicalCopilotGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "clinical_copilot_generation_failed", "reason": str(exc)},
        ) from exc
    return ApiResponse(data=result)
