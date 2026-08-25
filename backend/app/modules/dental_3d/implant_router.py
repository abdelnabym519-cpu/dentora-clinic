"""Thin FastAPI presentation layer for deterministic implant planning."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.patients.models import Patient

from .implant_planning import (
    DentalImplantPlanResponse,
    ImplantPlanCreate,
    ImplantPlanEdit,
    ImplantPlanningSnapshot,
    ImplantPlanReviewUpdate,
    ImplantProposalRequest,
    ProstheticTargetCreate,
    ProstheticTargetResponse,
    ProstheticTargetReviewUpdate,
)
from .implant_service import DentalImplantPlanningService, ImplantPlanningError

router = APIRouter()


async def _ensure_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> None:
    stmt = select(Patient).where(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
        Patient.status != "archived",
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")


def _conflict(exc: ImplantPlanningError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/patients/{patient_id}/implant-planning",
    response_model=ApiResponse[ImplantPlanningSnapshot],
)
async def get_implant_planning(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ImplantPlanningSnapshot]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    return ApiResponse(
        data=await DentalImplantPlanningService.snapshot(db, ctx.clinic_id, patient_id)
    )


@router.post(
    "/patients/{patient_id}/prosthetic-targets",
    response_model=ApiResponse[ProstheticTargetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_prosthetic_target(
    patient_id: UUID,
    payload: ProstheticTargetCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProstheticTargetResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await DentalImplantPlanningService.create_prosthetic_target(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            payload=payload,
        )
    except ImplantPlanningError as exc:
        raise _conflict(exc) from exc
    return ApiResponse(data=result)


@router.post(
    "/patients/{patient_id}/prosthetic-targets/{target_id}/review",
    response_model=ApiResponse[ProstheticTargetResponse],
)
async def review_prosthetic_target(
    patient_id: UUID,
    target_id: UUID,
    payload: ProstheticTargetReviewUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ProstheticTargetResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await DentalImplantPlanningService.review_prosthetic_target(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            target_id=target_id,
            reviewer_id=ctx.user_id,
            payload=payload,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prosthetic target not found"
        ) from exc
    except ImplantPlanningError as exc:
        raise _conflict(exc) from exc
    return ApiResponse(data=result)


@router.post(
    "/patients/{patient_id}/implant-plans",
    response_model=ApiResponse[DentalImplantPlanResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_implant_plan(
    patient_id: UUID,
    payload: ImplantPlanCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalImplantPlanResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await DentalImplantPlanningService.create_manual_plan(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            payload=payload,
        )
    except ImplantPlanningError as exc:
        raise _conflict(exc) from exc
    return ApiResponse(data=result)


@router.post(
    "/patients/{patient_id}/implant-plans/proposals",
    response_model=ApiResponse[DentalImplantPlanResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_deterministic_implant_proposal(
    patient_id: UUID,
    payload: ImplantProposalRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalImplantPlanResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await DentalImplantPlanningService.create_proposal(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            payload=payload,
        )
    except ImplantPlanningError as exc:
        raise _conflict(exc) from exc
    return ApiResponse(data=result)


@router.put(
    "/patients/{patient_id}/implant-plans/{plan_id}",
    response_model=ApiResponse[DentalImplantPlanResponse],
)
async def edit_implant_plan(
    patient_id: UUID,
    plan_id: UUID,
    payload: ImplantPlanEdit,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalImplantPlanResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await DentalImplantPlanningService.edit_plan(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            plan_id=plan_id,
            user_id=ctx.user_id,
            payload=payload,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Implant plan not found"
        ) from exc
    except ImplantPlanningError as exc:
        raise _conflict(exc) from exc
    return ApiResponse(data=result)


@router.post(
    "/patients/{patient_id}/implant-plans/{plan_id}/review",
    response_model=ApiResponse[DentalImplantPlanResponse],
)
async def review_implant_plan(
    patient_id: UUID,
    plan_id: UUID,
    payload: ImplantPlanReviewUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalImplantPlanResponse]:
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    try:
        result = await DentalImplantPlanningService.review_plan(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            plan_id=plan_id,
            reviewer_id=ctx.user_id,
            decision=payload.decision,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Implant plan not found"
        ) from exc
    except ImplantPlanningError as exc:
        raise _conflict(exc) from exc
    return ApiResponse(data=result)


__all__ = ["router"]
