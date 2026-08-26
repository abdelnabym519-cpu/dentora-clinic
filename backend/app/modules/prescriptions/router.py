"""FastAPI adapter for Electronic Prescription."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .domain import MedicationItem, PrescriptionError, PrescriptionStatus
from .repository import SqlAlchemyPatientAccess, SqlAlchemyPrescriptionRepository
from .schemas import (
    AuditEventResponse,
    PrescriptionCreate,
    PrescriptionResponse,
    PrescriptionUpdate,
    TransitionRequest,
)
from .use_cases import PrescriptionUseCases

router = APIRouter(tags=["Electronic Prescription"])


def _use_cases(db: AsyncSession) -> PrescriptionUseCases:
    return PrescriptionUseCases(
        SqlAlchemyPrescriptionRepository(db),
        SqlAlchemyPatientAccess(db),
    )


def _items(payload: PrescriptionCreate) -> tuple[MedicationItem, ...]:
    return tuple(
        MedicationItem(
            medication_name=item.medication_name,
            strength=item.strength,
            dose=item.dose,
            frequency=item.frequency,
            duration=item.duration,
            route=item.route,
            instructions=item.instructions,
            quantity=item.quantity,
            quantity_unit=item.quantity_unit,
        )
        for item in payload.items
    )


def _http_error(exc: PrescriptionError) -> HTTPException:
    detail = str(exc)
    if detail == "prescription not found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post("", response_model=ApiResponse[PrescriptionResponse], status_code=201)
async def create_prescription(
    payload: PrescriptionCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.write"))],
) -> ApiResponse[PrescriptionResponse]:
    try:
        rx = await _use_cases(db).create(
            tenant_id=ctx.tenant_id,
            clinic_id=ctx.clinic_id,
            patient_id=payload.patient_id,
            doctor_id=ctx.user_id,
            items=_items(payload),
        )
    except PrescriptionError as exc:
        raise _http_error(exc) from exc
    return ApiResponse(data=PrescriptionResponse.from_domain(rx))


@router.get("", response_model=ApiResponse[list[PrescriptionResponse]])
async def list_prescriptions(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.read"))],
    patient_id: UUID | None = None,
    prescription_status: Annotated[PrescriptionStatus | None, Query(alias="status")] = None,
) -> ApiResponse[list[PrescriptionResponse]]:
    rows = await _use_cases(db).list(
        tenant_id=ctx.tenant_id,
        clinic_id=ctx.clinic_id,
        patient_id=patient_id,
        status=prescription_status,
    )
    return ApiResponse(data=[PrescriptionResponse.from_domain(row) for row in rows])


@router.get("/{prescription_id}", response_model=ApiResponse[PrescriptionResponse])
async def get_prescription(
    prescription_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.read"))],
) -> ApiResponse[PrescriptionResponse]:
    try:
        rx = await _use_cases(db).get(
            prescription_id, tenant_id=ctx.tenant_id, clinic_id=ctx.clinic_id
        )
    except PrescriptionError as exc:
        raise _http_error(exc) from exc
    return ApiResponse(data=PrescriptionResponse.from_domain(rx))


@router.patch("/{prescription_id}", response_model=ApiResponse[PrescriptionResponse])
async def update_prescription(
    prescription_id: UUID,
    payload: PrescriptionUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.write"))],
) -> ApiResponse[PrescriptionResponse]:
    try:
        rx = await _use_cases(db).update(
            prescription_id,
            tenant_id=ctx.tenant_id,
            clinic_id=ctx.clinic_id,
            actor_id=ctx.user_id,
            patient_id=payload.patient_id,
            items=_items(payload),
        )
    except PrescriptionError as exc:
        raise _http_error(exc) from exc
    return ApiResponse(data=PrescriptionResponse.from_domain(rx))


@router.post("/{prescription_id}/issue", response_model=ApiResponse[PrescriptionResponse])
async def issue_prescription(
    prescription_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.issue"))],
) -> ApiResponse[PrescriptionResponse]:
    try:
        rx = await _use_cases(db).issue(
            prescription_id,
            tenant_id=ctx.tenant_id,
            clinic_id=ctx.clinic_id,
            actor_id=ctx.user_id,
        )
    except PrescriptionError as exc:
        raise _http_error(exc) from exc
    return ApiResponse(data=PrescriptionResponse.from_domain(rx))


@router.post("/{prescription_id}/cancel", response_model=ApiResponse[PrescriptionResponse])
async def cancel_prescription(
    prescription_id: UUID,
    payload: TransitionRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.cancel"))],
) -> ApiResponse[PrescriptionResponse]:
    try:
        rx = await _use_cases(db).cancel(
            prescription_id,
            tenant_id=ctx.tenant_id,
            clinic_id=ctx.clinic_id,
            actor_id=ctx.user_id,
            reason=payload.reason,
        )
    except PrescriptionError as exc:
        raise _http_error(exc) from exc
    return ApiResponse(data=PrescriptionResponse.from_domain(rx))


@router.post("/{prescription_id}/void", response_model=ApiResponse[PrescriptionResponse])
async def void_prescription(
    prescription_id: UUID,
    payload: TransitionRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.void"))],
) -> ApiResponse[PrescriptionResponse]:
    try:
        rx = await _use_cases(db).void(
            prescription_id,
            tenant_id=ctx.tenant_id,
            clinic_id=ctx.clinic_id,
            actor_id=ctx.user_id,
            reason=payload.reason,
        )
    except PrescriptionError as exc:
        raise _http_error(exc) from exc
    return ApiResponse(data=PrescriptionResponse.from_domain(rx))


@router.get("/{prescription_id}/audit", response_model=ApiResponse[list[AuditEventResponse]])
async def prescription_audit(
    prescription_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_permission("prescriptions.audit"))],
) -> ApiResponse[list[AuditEventResponse]]:
    try:
        events = await _use_cases(db).audit(
            prescription_id, tenant_id=ctx.tenant_id, clinic_id=ctx.clinic_id
        )
    except PrescriptionError as exc:
        raise _http_error(exc) from exc
    return ApiResponse(data=[AuditEventResponse(**event) for event in events])
