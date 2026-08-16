"""HTTP routes for staff booking settings and public patient booking."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import (
    ClinicContext,
    get_clinic_context,
    require_permission,
)
from app.core.auth.router import limiter
from app.core.schemas import ApiResponse
from app.core.trial import ensure_trial_active
from app.database import get_db

from .models import BookingSettings
from .schemas import (
    BookingSettingsResponse,
    BookingSettingsUpdate,
    PublicBookableSlot,
    PublicBookingClinic,
    PublicBookingCreate,
    PublicBookingResponse,
    PublicProfessional,
)
from .service import BookingService, BookingUnavailableError

router = APIRouter()


# ---------------------------------------------------------------------------
# Staff settings
# ---------------------------------------------------------------------------


@router.get(
    "/settings",
    response_model=ApiResponse[BookingSettingsResponse],
)
async def get_booking_settings(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[
        None,
        Depends(require_permission("booking.settings.read")),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[BookingSettingsResponse]:
    settings = await BookingService.get_settings_for_clinic(
        db,
        ctx.clinic_id,
    )

    if settings is None:
        return ApiResponse(
            data=BookingSettingsResponse(
                enabled=False,
                public_slug=None,
                slot_minutes=30,
                days_ahead=30,
            )
        )

    return ApiResponse(
        data=BookingSettingsResponse(
            enabled=settings.enabled,
            public_slug=settings.public_slug,
            slot_minutes=settings.slot_minutes,
            days_ahead=settings.days_ahead,
        )
    )


@router.put(
    "/settings",
    response_model=ApiResponse[BookingSettingsResponse],
)
async def update_booking_settings(
    payload: BookingSettingsUpdate,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[
        None,
        Depends(require_permission("booking.settings.write")),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[BookingSettingsResponse]:
    settings = await BookingService.get_settings_for_clinic(
        db,
        ctx.clinic_id,
    )

    if settings is None:
        settings = BookingSettings(clinic_id=ctx.clinic_id)
        db.add(settings)

    updates = payload.model_dump(exclude_unset=True)

    if "public_slug" in updates and updates["public_slug"] is not None:
        updates["public_slug"] = updates["public_slug"].strip().lower()

    for field, value in updates.items():
        setattr(settings, field, value)

    if settings.enabled and not settings.public_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A public slug is required before enabling online booking",
        )

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This public booking slug is already in use",
        ) from exc

    return ApiResponse(
        data=BookingSettingsResponse(
            enabled=settings.enabled,
            public_slug=settings.public_slug,
            slot_minutes=settings.slot_minutes,
            days_ahead=settings.days_ahead,
        )
    )


# ---------------------------------------------------------------------------
# Public endpoints — no staff authentication
# ---------------------------------------------------------------------------


async def _public_settings_or_404(
    db: AsyncSession,
    slug: str,
) -> BookingSettings:
    # Hosted trials are deployment-scoped. Public booking must expire with
    # the staff application so a trial cannot keep accepting appointments
    # after the three-day window has ended.
    ensure_trial_active()

    settings = await BookingService.get_settings_by_slug(
        db,
        slug.strip().lower(),
    )

    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Online booking link not found",
        )

    return settings


@router.get(
    "/public/{slug}",
    response_model=ApiResponse[PublicBookingClinic],
)
@limiter.limit("60/minute")
async def get_public_booking_clinic(
    slug: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PublicBookingClinic]:
    settings = await _public_settings_or_404(db, slug)

    clinic = await BookingService.get_clinic(
        db,
        settings.clinic_id,
    )
    if clinic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clinic not found",
        )

    return ApiResponse(
        data=PublicBookingClinic(
            clinic_name=clinic.name,
            clinic_phone=clinic.phone,
            clinic_email=clinic.email,
            timezone=clinic.timezone,
            currency=clinic.currency,
            slot_minutes=settings.slot_minutes,
            days_ahead=settings.days_ahead,
        )
    )


@router.get(
    "/public/{slug}/professionals",
    response_model=ApiResponse[list[PublicProfessional]],
)
@limiter.limit("60/minute")
async def get_public_professionals(
    slug: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[PublicProfessional]]:
    settings = await _public_settings_or_404(db, slug)

    professionals = await BookingService.list_public_professionals(
        db,
        settings.clinic_id,
    )

    return ApiResponse(
        data=[
            PublicProfessional(
                id=professional.id,
                first_name=professional.first_name,
                last_name=professional.last_name,
            )
            for professional in professionals
        ]
    )


@router.get(
    "/public/{slug}/slots",
    response_model=ApiResponse[list[PublicBookableSlot]],
)
@limiter.limit("30/minute")
async def get_public_slots(
    slug: str,
    professional_id: UUID,
    day: date,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[PublicBookableSlot]]:
    settings = await _public_settings_or_404(db, slug)

    _, slots = await BookingService.get_bookable_slots(
        db,
        settings,
        professional_id,
        day,
    )

    return ApiResponse(
        data=[
            PublicBookableSlot(
                start=start,
                end=end,
            )
            for start, end in slots
        ]
    )


@router.post(
    "/public/{slug}",
    response_model=ApiResponse[PublicBookingResponse],
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/15minute")
async def create_public_booking(
    slug: str,
    payload: PublicBookingCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[PublicBookingResponse]:
    settings = await _public_settings_or_404(db, slug)

    try:
        appointment, professional = await BookingService.create_public_booking(
            db,
            settings,
            payload,
        )
    except BookingUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return ApiResponse(
        data=PublicBookingResponse(
            appointment_id=appointment.id,
            start_time=appointment.start_time,
            end_time=appointment.end_time,
            professional_name=(f"{professional.first_name} {professional.last_name}").strip(),
            status=appointment.status,
        )
    )
