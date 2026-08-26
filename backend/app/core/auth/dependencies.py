"""Authentication dependencies for FastAPI."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.log_context import set_request_context
from app.core.tenancy.adapters import SqlAlchemyTenantAdapter
from app.core.tenancy.selection import ClinicSelectionError, select_clinic
from app.core.trial import ensure_trial_active
from app.database import get_db

from .models import Clinic, ClinicMembership, User
from .permissions import has_permission
from .service import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class ClinicContext:
    """Context object containing current user, tenant and clinic."""

    def __init__(
        self,
        user: User,
        clinic: Clinic,
        role: str,
        *,
        tenant_id: UUID,
        is_platform_admin: bool = False,
    ) -> None:
        self.user = user
        self.clinic = clinic
        self.role = role
        self.clinic_id = clinic.id
        self.user_id = user.id
        # Tenant that owns the selected clinic. Defense-in-depth anchor
        # for repository/service checks that want to assert cross-clinic
        # isolation at the data layer.
        self.tenant_id = tenant_id
        self.is_platform_admin = is_platform_admin

    def assert_clinic(self, clinic_id: UUID) -> None:
        """Reject access to a clinic other than the selected one.

        Repository/service-level defense in depth: any code that accepts
        a ``clinic_id`` parameter (not just the context's own) calls this
        before reading/writing so a missing ``WHERE clinic_id`` in a
        query cannot leak across clinics.
        """
        if clinic_id != self.clinic_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-clinic access denied",
            )


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        token_version = payload.get("token_version", 0)

        if user_id is None or token_type != "access":
            raise credentials_exception

        # Stash JWT selection claims on request.state so the clinic
        # resolver can use them as a low-priority default.
        request.state.jwt_clinic_id = payload.get("clinic_id")
        request.state.tenant_slug = payload.get("tenant_slug")

    except JWTError:
        raise credentials_exception

    # Fetch user from database
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Check token version for revocation
    if user.token_version != token_version:
        raise credentials_exception

    return user


def _requested_clinic_id(
    request: Request,
    explicit: UUID | None,
) -> UUID | None:
    """Resolve the caller's requested clinic from all available hints.

    Precedence: explicit dependency value (query param / body) wins,
    then the ``X-Clinic-Id`` header, then the JWT ``clinic_id`` claim.
    A malformed id is treated as "no selection" rather than 500 so the
    downstream membership check produces a clean 403.
    """
    if explicit is not None:
        return explicit
    raw = request.headers.get(settings.CLINIC_HEADER)
    if raw:
        try:
            return UUID(raw)
        except (ValueError, AttributeError):
            return None
    jwt_clinic = getattr(request.state, "jwt_clinic_id", None)
    if jwt_clinic:
        try:
            return UUID(str(jwt_clinic))
        except (ValueError, AttributeError):
            return None
    return None


async def get_clinic_context(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    clinic_id: UUID | None = None,
) -> ClinicContext:
    """Resolve the effective tenant + clinic for the request.

    The selected clinic is computed from the user's *memberships* and
    the explicit selection (``X-Clinic-Id`` header, query param, or JWT
    claim) — **never** blindly from the first membership. Permissions
    are then derived from the role held in *that* clinic, so a user who
    is a dentist in clinic A and a receptionist in clinic B gets the
    right grant set for the clinic they chose.
    """
    from app.core.auth.models import Clinic as ClinicModel

    # Eager-load clinic + its tenant + cabinets so selection/serialization
    # don't trigger async lazy loads downstream.
    result = await db.execute(
        select(ClinicMembership)
        .options(
            selectinload(ClinicMembership.clinic).selectinload(ClinicModel.tenant),
            selectinload(ClinicMembership.clinic).selectinload(ClinicModel.cabinets),
        )
        .where(ClinicMembership.user_id == current_user.id)
    )
    memberships = result.scalars().all()

    # Platform (super) admins may not hold a clinic membership for the
    # clinic they are managing — they resolve through the same path but
    # are allowed to target any clinic by id. Read their target from
    # the memberships if possible; otherwise load it explicitly.
    requested = _requested_clinic_id(request, clinic_id)

    if not memberships and not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any clinic",
        )

    # Map SQLAlchemy memberships to the immutable records the domain
    # selection logic operates on.
    adapter = SqlAlchemyTenantAdapter(db)
    records = await adapter.list_memberships(current_user.id)

    target_clinic: Clinic | None = None
    role: str

    try:
        if current_user.is_platform_admin and requested is not None and not records:
            # Pure platform admin impersonating / managing a clinic
            # without a membership of their own.
            clinic_result = await db.execute(
                select(ClinicModel)
                .where(ClinicModel.id == requested)
                .options(
                    selectinload(ClinicModel.tenant),
                    selectinload(ClinicModel.cabinets),
                )
            )
            target_clinic = clinic_result.scalar_one_or_none()
            if target_clinic is None or target_clinic.tenant is None:
                raise ClinicSelectionError("Requested clinic does not exist")
            if not target_clinic.is_active:
                raise ClinicSelectionError("Requested clinic is suspended")
            role = "admin"
            tenant_id = target_clinic.tenant.id
        else:
            selected = select_clinic(
                records,
                requested_clinic_id=requested,
            )
            # Load the full Clinic ORM object for downstream endpoints.
            clinic_result = await db.execute(
                select(ClinicModel)
                .where(ClinicModel.id == selected.clinic_id)
                .options(
                    selectinload(ClinicModel.tenant),
                    selectinload(ClinicModel.cabinets),
                )
            )
            target_clinic = clinic_result.scalar_one()
            role = selected.role
            tenant_id = selected.tenant_id
    except ClinicSelectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    # Trial mode is deployment-scoped. Paid/offline installations leave
    # it disabled; hosted demos are rejected after the configured window.
    ensure_trial_active()

    # Bind clinic_id + user_id onto the per-request logging context.
    set_request_context(clinic_id=target_clinic.id, user_id=current_user.id)

    return ClinicContext(
        user=current_user,
        clinic=target_clinic,
        role=role,
        tenant_id=tenant_id,
        is_platform_admin=bool(current_user.is_platform_admin),
    )


def require_permission(permission: str) -> Callable:
    """FastAPI dependency factory that requires a specific permission.

    Platform admins implicitly satisfy every clinic permission check
    (they administer the deployment), while regular users are gated by
    the role held in the *selected* clinic.

    Usage:
        @router.get("/patients")
        async def list_patients(
            ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
            _: Annotated[None, Depends(require_permission("clinical.patients.read"))],
        ):
            ...
    """

    async def permission_checker(
        ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    ) -> None:
        if ctx.is_platform_admin:
            return
        if not has_permission(ctx.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}",
            )

    return permission_checker
