"""HTTP API for read-only Clinical Copilot evidence and advice."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.license.dependencies import require_license_feature
from app.core.llm import LLMConfigError, get_provider
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.copilot.models import CopilotSettings

from .contracts import ClinicalCopilotAdvisory, ClinicalCopilotAsk, ClinicalCopilotContext
from .service import (
    ClinicalContextInsufficientError,
    ClinicalCopilotOutputError,
    ClinicalCopilotService,
)

router = APIRouter(dependencies=[Depends(require_license_feature("ai"))])


@router.get(
    "/patients/{patient_id}/context",
    response_model=ApiResponse[ClinicalCopilotContext],
)
async def get_context(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("clinical_copilot.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicalCopilotContext]:
    context = await ClinicalCopilotService(db).build_context(
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
    )
    return ApiResponse(data=context)


@router.post("/advise", response_model=ApiResponse[ClinicalCopilotAdvisory])
async def advise(
    body: ClinicalCopilotAsk,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("clinical_copilot.use"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicalCopilotAdvisory]:
    configured = await db.get(CopilotSettings, ctx.clinic_id)
    provider_name = configured.provider if configured else app_settings.COPILOT_PROVIDER_DEFAULT
    model = configured.model if configured else app_settings.COPILOT_MODEL_CHAT_OPENAI
    try:
        provider = get_provider(provider_name)
        result = await ClinicalCopilotService(db).advise(
            clinic_id=ctx.clinic_id,
            patient_id=body.patient_id,
            question=body.focus,
            provider=provider,
            provider_name=provider_name,
            model=model,
        )
    except ClinicalContextInsufficientError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "clinical_context_insufficient",
                "missing_or_stale": exc.context.missing_or_stale,
                "context": exc.context.model_dump(mode="json"),
            },
        ) from exc
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "clinical_copilot_provider_unavailable", "message": str(exc)},
        ) from exc
    except ClinicalCopilotOutputError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": str(exc)},
        ) from exc
    return ApiResponse(data=result)
