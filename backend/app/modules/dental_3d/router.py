"""Dental 3D FastAPI router.

Mounted at ``/api/v1/dental_3d/`` by the module loader. Thin router —
logic lives in the service.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db
from app.modules.patients.models import Patient

from .meshfiles import MeshUploadError
from .schemas import DentalMesh, DentalSceneResponse, DentalSceneUpdate
from .service import DentalMeshService, DentalSceneService

router = APIRouter()


async def _ensure_patient(db: AsyncSession, clinic_id: UUID, patient_id: UUID) -> None:
    """Mirror the odontogram pattern: 404 if patient is missing/archived."""
    stmt = select(Patient).where(
        Patient.id == patient_id,
        Patient.clinic_id == clinic_id,
        Patient.status != "archived",
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")


@router.get(
    "/patients/{patient_id}/scene",
    response_model=ApiResponse[DentalSceneResponse],
)
async def get_patient_scene(
    patient_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalSceneResponse]:
    """Return the patient's 3D scene (synthesised + persisted view state)."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    scene = await DentalSceneService.get_for_patient(db, ctx.clinic_id, patient_id)
    return ApiResponse(data=scene)


@router.put(
    "/patients/{patient_id}/scene",
    response_model=ApiResponse[DentalSceneResponse],
)
async def save_patient_scene(
    patient_id: UUID,
    data: DentalSceneUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("dental_3d.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DentalSceneResponse]:
    """Persist per-tooth 3D view state (full replace)."""
    await _ensure_patient(db, ctx.clinic_id, patient_id)
    scene = await DentalSceneService.save_for_patient(
        db, ctx.clinic_id, patient_id, ctx.user_id, data
    )
    return ApiResponse(data=scene)


@router.post(
    "/patients/{patient_id}/meshes",
    response_model=ApiResponse[DentalMesh],
    status_code=status.HTTP_201_CREATED,
)
async def upload_patient_mesh(
    patient_id: UUID,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)] = None,
    _: Annotated[None, Depends(require_permission("dental_3d.write"))] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ApiResponse[DentalMesh]:
    """Ingest a real mesh file (STL / OBJ) as the patient's scan geometry.

    Validation (extension + MIME + content sniff + size) happens in the
    service; storage goes through the media module — this endpoint
    never touches the filesystem. Patient/clinic ownership is resolved
    server-side from the authenticated context.
    """
    await _ensure_patient(db, ctx.clinic_id, patient_id)

    data = await file.read()
    try:
        mesh = await DentalMeshService.ingest(
            db,
            clinic_id=ctx.clinic_id,
            patient_id=patient_id,
            user_id=ctx.user_id,
            filename=file.filename or "scan",
            content_type=file.content_type,
            data=data,
            title=title,
        )
    except MeshUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=mesh)
