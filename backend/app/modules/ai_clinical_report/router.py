"""HTTP API for readiness checks and non-canonical AI Clinical Report drafts."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.license.dependencies import require_license_feature
from app.core.llm import LLMConfigError, get_default_model, get_provider
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.clinical_copilot.guarded import (
    ClinicalCopilotInputError,
)
from app.modules.clinical_copilot.service import (
    ClinicalContextInsufficientError,
    ClinicalCopilotOutputError,
)
from app.modules.copilot.models import CopilotSettings

from .contracts import AIClinicalReport, AIClinicalReportReadiness, AIClinicalReportRequest
from .service import AIClinicalReportService, ClinicalReportAssemblyError

router = APIRouter(dependencies=[Depends(require_license_feature("ai"))])


def _enforce_dentist_control(role: str) -> None:
    if role != "dentist":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "dentist_control_required"},
        )


@router.get(
    "/patients/{patient_id}/readiness",
    response_model=ApiResponse[AIClinicalReportReadiness],
)
async def readiness(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_clinical_report.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AIClinicalReportReadiness]:
    result = await AIClinicalReportService(db).readiness(
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
    )
    return ApiResponse(data=result)


@router.post("/generate", response_model=ApiResponse[AIClinicalReport])
async def generate(
    body: AIClinicalReportRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("ai_clinical_report.generate"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AIClinicalReport]:
    _enforce_dentist_control(ctx.role)
    configured = await db.get(CopilotSettings, ctx.clinic_id)
    provider_name = configured.provider if configured else app_settings.COPILOT_PROVIDER_DEFAULT
    model = configured.model if configured else get_default_model(provider_name)
    try:
        provider = get_provider(provider_name)
        report = await AIClinicalReportService(db).generate(
            clinic_id=ctx.clinic_id,
            patient_id=body.patient_id,
            provider=provider,
            provider_name=provider_name,
            model=model,
            user_id=ctx.user_id,
            user_role=ctx.role,
        )
    except ClinicalCopilotInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": str(exc)},
        ) from exc
    except ClinicalContextInsufficientError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "clinical_context_insufficient",
                "missing_or_stale": exc.context.missing_or_stale,
            },
        ) from exc
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ai_clinical_report_provider_unavailable", "message": str(exc)},
        ) from exc
    except (ClinicalCopilotOutputError, ClinicalReportAssemblyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": str(exc)},
        ) from exc
    return ApiResponse(data=report)
