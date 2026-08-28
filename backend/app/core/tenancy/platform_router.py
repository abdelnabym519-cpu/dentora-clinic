"""Platform (super) admin HTTP API for tenant / clinic provisioning.

These endpoints are reachable only by users with
``users.is_platform_admin = True``. They sit *outside* the clinic-scoped
``ClinicContext`` because they operate across tenants and clinics;
authentication is still enforced via ``get_current_user``.

Following Screaming Architecture, the router is a thin adapter: it
translates HTTP → commands, delegates to the use cases in
``provisioning``, and translates domain errors to status codes. It
contains no business logic of its own.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import get_current_user
from app.core.auth.models import Clinic, User
from app.core.auth.service import hash_password
from app.core.schemas import ApiResponse, PaginatedApiResponse
from app.database import get_db

from .adapters import SqlAlchemyTenantAdapter
from .models import Tenant
from .provisioning import (
    AssignMembership,
    ProvisionClinic,
    ProvisionClinicCommand,
    ProvisionMembershipCommand,
    ProvisionTenant,
    ProvisionTenantCommand,
    TenantProvisioningError,
)

router = APIRouter(prefix="/platform", tags=["platform-admin"])


def require_platform_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency that rejects non-platform-admins."""
    if not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin privileges required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)


class TenantResponse(BaseModel):
    id: UUID
    slug: str
    display_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class ClinicCreate(BaseModel):
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    tax_id: str = Field(min_length=1, max_length=20)
    legal_name: str | None = Field(default=None, max_length=200)
    timezone: str = "Europe/Madrid"
    currency: str = Field(default="EUR", pattern="^[A-Z]{3}$")


class ClinicResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    tax_id: str
    is_active: bool

    model_config = {"from_attributes": True}


class MembershipCreate(BaseModel):
    user_email: EmailStr
    clinic_id: UUID
    role: str


class PlatformUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    is_platform_admin: bool = False
    role: str | None = Field(
        default=None,
        description="When set with clinic_id, grants a clinic membership too.",
    )
    clinic_id: UUID | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tenants", response_model=PaginatedApiResponse[TenantResponse])
async def list_tenants(
    _: Annotated[User, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PaginatedApiResponse[TenantResponse]:
    result = await db.execute(select(Tenant).order_by(Tenant.slug))
    tenants = result.scalars().all()
    data = [TenantResponse.model_validate(t) for t in tenants]
    return PaginatedApiResponse(data=data, total=len(data), page=1, page_size=len(data))


@router.post("/tenants", response_model=ApiResponse[TenantResponse], status_code=201)
async def create_tenant(
    payload: TenantCreate,
    _: Annotated[User, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TenantResponse]:
    adapter = SqlAlchemyTenantAdapter(db)
    try:
        record = await ProvisionTenant(adapter).execute(
            ProvisionTenantCommand(slug=payload.slug, display_name=payload.display_name)
        )
        await db.commit()
    except TenantProvisioningError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(
        data=TenantResponse(
            id=record.id,
            slug=record.slug,
            display_name=record.display_name,
            is_active=record.is_active,
        )
    )


@router.get("/clinics", response_model=PaginatedApiResponse[ClinicResponse])
async def list_clinics(
    _: Annotated[User, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PaginatedApiResponse[ClinicResponse]:
    result = await db.execute(select(Clinic).order_by(Clinic.name))
    clinics = result.scalars().all()
    data = [ClinicResponse.model_validate(c) for c in clinics]
    return PaginatedApiResponse(data=data, total=len(data), page=1, page_size=len(data))


@router.post("/clinics", response_model=ApiResponse[ClinicResponse], status_code=201)
async def create_clinic(
    payload: ClinicCreate,
    _: Annotated[User, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ClinicResponse]:
    adapter = SqlAlchemyTenantAdapter(db)
    try:
        clinic_id = await ProvisionClinic(adapter).execute(
            ProvisionClinicCommand(
                tenant_id=payload.tenant_id,
                name=payload.name,
                tax_id=payload.tax_id,
                legal_name=payload.legal_name,
                timezone=payload.timezone,
                currency=payload.currency,
            )
        )
        await db.commit()
    except TenantProvisioningError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
    clinic = result.scalar_one()
    return ApiResponse(data=ClinicResponse.model_validate(clinic))


@router.post("/clinics/{clinic_id}/members", status_code=201)
async def add_member(
    clinic_id: UUID,
    payload: MembershipCreate,
    _: Annotated[User, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    result = await db.execute(select(User).where(User.email == payload.user_email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.clinic_id != clinic_id:
        raise HTTPException(status_code=422, detail="Clinic id mismatch")
    adapter = SqlAlchemyTenantAdapter(db)
    try:
        await AssignMembership(adapter).execute(
            ProvisionMembershipCommand(user_id=user.id, clinic_id=clinic_id, role=payload.role)
        )
        await db.commit()
    except TenantProvisioningError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data={"user_id": str(user.id), "clinic_id": str(clinic_id)})


@router.post("/users", response_model=ApiResponse[dict], status_code=201)
async def create_platform_user(
    payload: PlatformUserCreate,
    _: Annotated[User, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict]:
    """Create a user, optionally marking them platform admin and/or
    attaching them to a clinic with a role."""
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        is_platform_admin=payload.is_platform_admin,
    )
    db.add(user)
    await db.flush()
    if payload.clinic_id and payload.role:
        adapter = SqlAlchemyTenantAdapter(db)
        try:
            await AssignMembership(adapter).execute(
                ProvisionMembershipCommand(
                    user_id=user.id, clinic_id=payload.clinic_id, role=payload.role
                )
            )
        except TenantProvisioningError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return ApiResponse(data={"id": str(user.id), "is_platform_admin": user.is_platform_admin})
