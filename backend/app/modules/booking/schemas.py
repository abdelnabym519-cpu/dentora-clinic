"""Pydantic schemas for public online booking."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

# ---------------------------------------------------------------------------
# Staff settings
# ---------------------------------------------------------------------------


class BookingSettingsResponse(BaseModel):
    enabled: bool
    public_slug: str | None
    slot_minutes: int
    days_ahead: int


class BookingSettingsUpdate(BaseModel):
    enabled: bool | None = None
    public_slug: str | None = Field(
        default=None,
        min_length=3,
        max_length=120,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    slot_minutes: int | None = Field(default=None, ge=5, le=240)
    days_ahead: int | None = Field(default=None, ge=1, le=180)


# ---------------------------------------------------------------------------
# Public read-only data
# ---------------------------------------------------------------------------


class PublicBookingClinic(BaseModel):
    clinic_name: str
    clinic_phone: str | None = None
    clinic_email: str | None = None
    timezone: str
    currency: str
    slot_minutes: int
    days_ahead: int


class PublicProfessional(BaseModel):
    id: UUID
    first_name: str
    last_name: str


class PublicBookableSlot(BaseModel):
    start: datetime
    end: datetime


# ---------------------------------------------------------------------------
# Public booking creation
# ---------------------------------------------------------------------------


class PublicBookingCreate(BaseModel):
    professional_id: UUID
    start_time: datetime

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=7, max_length=20)
    date_of_birth: date
    email: EmailStr | None = None

    reason: str | None = Field(default=None, max_length=500)


class PublicBookingResponse(BaseModel):
    appointment_id: UUID
    start_time: datetime
    end_time: datetime
    professional_name: str
    status: str
