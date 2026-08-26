"""Patient HTTP surface.

Mounts under ``/api/v1/patients/*``. Permissions live in the
``patients.*`` namespace: ``patients.read`` and ``patients.write``.

The router is also the module's composition boundary: FastAPI/SQLAlchemy
dependencies are adapted into application ports here and never leak into
``PatientService``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .event_publisher import EventBusPatientEventPublisher
from .repository import SqlAlchemyPatientRepository
from .schemas import (
    PatientCreate,
    PatientExtendedResponse,
    PatientExtendedUpdate,
    PatientResponse,
    PatientUpdate,
)
from .service import InvalidPatientSortError, PatientService

router = APIRouter()


def get_patient_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientService:
    """Compose the patient use cases with infrastructure adapters."""
    return PatientService(
        repository=SqlAlchemyPatientRepository(db),
        events=EventBusPatientEventPublisher(),
    )


PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]


def _raise_sort_http_error(exc: InvalidPatientSortError) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    ) from exc


@router.get("/recent", response_model=ApiResponse[list[PatientResponse]])
async def get_recent_patients(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.read"))],
    service: PatientServiceDep,
    limit: int = Query(default=8, ge=1, le=20),
) -> ApiResponse[list[PatientResponse]]:
    """Get recent patients (by last visit or creation date)."""
    patients = await service.get_recent_patients(ctx.clinic_id, limit)
    return ApiResponse(data=[PatientResponse.model_validate(patient) for patient in patients])


@router.get("", response_model=PaginatedApiResponse[PatientResponse])
async def list_patients(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.read"))],
    service: PatientServiceDep,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    patient_ids: list[UUID] | None = Query(default=None),
    city: str | None = Query(default=None, max_length=100),
    do_not_contact: bool | None = Query(default=None),
    include_archived: bool = Query(default=False),
    sort: str | None = Query(default=None, max_length=50),
) -> PaginatedApiResponse[PatientResponse]:
    """List patients with optional search + filters."""
    try:
        patients, total = await service.list_patients(
            ctx.clinic_id,
            search,
            page,
            page_size,
            patient_ids=patient_ids,
            city=city,
            do_not_contact=do_not_contact,
            include_archived=include_archived,
            sort=sort,
        )
    except InvalidPatientSortError as exc:
        _raise_sort_http_error(exc)

    return PaginatedApiResponse(
        data=[PatientResponse.model_validate(patient) for patient in patients],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=ApiResponse[PatientResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_patient(
    data: PatientCreate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.write"))],
    service: PatientServiceDep,
) -> ApiResponse[PatientResponse]:
    """Create a new patient."""
    patient = await service.create_patient(
        ctx.clinic_id,
        data.model_dump(exclude_unset=True),
    )
    return ApiResponse(data=PatientResponse.model_validate(patient))


@router.get("/{patient_id}", response_model=ApiResponse[PatientResponse])
async def get_patient(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.read"))],
    service: PatientServiceDep,
) -> ApiResponse[PatientResponse]:
    """Get a patient by ID."""
    patient = await service.get_patient(ctx.clinic_id, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    return ApiResponse(data=PatientResponse.model_validate(patient))


@router.put("/{patient_id}", response_model=ApiResponse[PatientResponse])
async def update_patient(
    patient_id: UUID,
    data: PatientUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.write"))],
    service: PatientServiceDep,
) -> ApiResponse[PatientResponse]:
    """Update a patient."""
    patient = await service.update_patient(
        ctx.clinic_id,
        patient_id,
        data.model_dump(exclude_unset=True),
    )
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    return ApiResponse(data=PatientResponse.model_validate(patient))


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.write"))],
    service: PatientServiceDep,
) -> None:
    """Soft delete (archive) a patient."""
    patient = await service.archive_patient(ctx.clinic_id, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )


# --- Extended info ------------------------------------------------------


@router.get("/{patient_id}/extended", response_model=ApiResponse[PatientExtendedResponse])
async def get_patient_extended(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.read"))],
    service: PatientServiceDep,
) -> ApiResponse[PatientExtendedResponse]:
    """Get patient with extended identity/demographics info."""
    patient = await service.get_patient(ctx.clinic_id, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    return ApiResponse(data=PatientExtendedResponse.model_validate(patient))


@router.put("/{patient_id}/extended", response_model=ApiResponse[PatientExtendedResponse])
async def update_patient_extended(
    patient_id: UUID,
    data: PatientExtendedUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("patients.write"))],
    service: PatientServiceDep,
) -> ApiResponse[PatientExtendedResponse]:
    """Update patient with extended demographic fields."""
    patient = await service.update_patient(
        ctx.clinic_id,
        patient_id,
        data.model_dump(exclude_unset=True),
    )
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )
    return ApiResponse(data=PatientExtendedResponse.model_validate(patient))
