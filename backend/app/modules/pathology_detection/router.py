"""Pathology detection FastAPI router.

Mounted at ``/api/v1/pathology_detection/`` by the module loader.

Endpoints:
* ``GET  /capabilities``                          — engine availability
* ``POST /patients/{patient_id}/analyses``        — run on a media doc
* ``GET  /patients/{patient_id}/analyses``        — history
* ``GET  /analyses/{analysis_id}``                — detail incl. findings
* ``DELETE /analyses/{analysis_id}``              — remove a run
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .engine import EngineUnavailableError, engine_capabilities
from .schemas import (
    AnalysisCreate,
    AnalysisDetail,
    AnalysisSummary,
    CapabilitiesResponse,
    FindingResponse,
)
from .service import PathologyDetectionService

router = APIRouter()


def _detail(analysis) -> AnalysisDetail:
    return AnalysisDetail(
        id=analysis.id,
        patient_id=analysis.patient_id,
        document_id=analysis.document_id,
        status=analysis.status,
        engine=analysis.engine,
        model_version=analysis.model_version,
        image_width=analysis.image_width,
        image_height=analysis.image_height,
        findings_count=analysis.findings_count,
        inference_ms=analysis.inference_ms,
        summary=analysis.summary,
        notes=analysis.notes,
        created_by=analysis.created_by,
        created_at=analysis.created_at,
        error=analysis.error,
        findings=[FindingResponse.model_validate(f) for f in analysis.findings],
    )


@router.get("/capabilities", response_model=ApiResponse[CapabilitiesResponse])
async def get_capabilities(
    _ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    __: Annotated[None, Depends(require_permission("pathology_detection.read"))],
) -> ApiResponse[CapabilitiesResponse]:
    """Advertise whether the AI engine is provisioned."""
    return ApiResponse(data=CapabilitiesResponse(**engine_capabilities()))


@router.post(
    "/patients/{patient_id}/analyses",
    response_model=ApiResponse[AnalysisDetail],
    status_code=status.HTTP_201_CREATED,
)
async def run_analysis(
    patient_id: UUID,
    payload: AnalysisCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("pathology_detection.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AnalysisDetail]:
    service = PathologyDetectionService(db)
    if not await service.get_patient(ctx.clinic_id, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        analysis = await service.run_analysis(
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            document_id=payload.document_id,
            created_by=ctx.user_id,
            notes=payload.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Document not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except EngineUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # inference failure — persisted as failed by the service
        raise HTTPException(status_code=500, detail=f"Pathology analysis failed: {exc}")

    return ApiResponse(data=_detail(analysis))


@router.get(
    "/patients/{patient_id}/analyses",
    response_model=ApiResponse[list[AnalysisSummary]],
)
async def list_analyses(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("pathology_detection.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[AnalysisSummary]]:
    service = PathologyDetectionService(db)
    if not await service.get_patient(ctx.clinic_id, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    analyses = await service.list_analyses(ctx.clinic_id, patient_id)
    return ApiResponse(
        data=[AnalysisSummary.model_validate(a) for a in analyses],
    )


@router.get("/analyses/{analysis_id}", response_model=ApiResponse[AnalysisDetail])
async def get_analysis(
    analysis_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("pathology_detection.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[AnalysisDetail]:
    service = PathologyDetectionService(db)
    analysis = await service.get_analysis(ctx.clinic_id, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return ApiResponse(data=_detail(analysis))


@router.delete("/analyses/{analysis_id}", response_model=ApiResponse[None])
async def delete_analysis(
    analysis_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("pathology_detection.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    service = PathologyDetectionService(db)
    analysis = await service.get_analysis(ctx.clinic_id, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    await service.delete_analysis(analysis)
    return ApiResponse(data=None)
