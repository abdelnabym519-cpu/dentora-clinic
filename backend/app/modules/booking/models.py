"""Database models for the online booking module."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class BookingSettings(Base, TimestampMixin):
    """Per-clinic public booking configuration."""

    __tablename__ = "booking_settings"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Public URL: /booking/<public_slug>
    # Nullable until the clinic explicitly enables/configures booking.
    public_slug: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        unique=True,
        index=True,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # Default appointment duration exposed to patients.
    slot_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )

    # How far into the future patients may book.
    days_ahead: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )


class BookingCloudRequest(Base, TimestampMixin):
    """Durable local receipt for an at-least-once cloud booking request."""

    __tablename__ = "booking_cloud_requests"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    clinic_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Cloud request IDs are treated as opaque identifiers.
    request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    # Local lifecycle only. Cloud remains authoritative for its own
    # pending/delivered/accepted/rejected state.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="processing",
        server_default="processing",
    )

    appointment_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id"),
        nullable=True,
    )

    rejection_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "request_id",
            name="uq_booking_cloud_requests_clinic_request",
        ),
        CheckConstraint(
            "status IN ('processing', 'accepted', 'rejected')",
            name="ck_booking_cloud_requests_status",
        ),
        CheckConstraint(
            """
            (
                status = 'processing'
                AND appointment_id IS NULL
                AND rejection_code IS NULL
            )
            OR
            (
                status = 'accepted'
                AND appointment_id IS NOT NULL
                AND rejection_code IS NULL
            )
            OR
            (
                status = 'rejected'
                AND appointment_id IS NULL
                AND rejection_code IS NOT NULL
            )
            """,
            name="ck_booking_cloud_requests_result_shape",
        ),
    )
