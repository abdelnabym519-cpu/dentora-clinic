"""Local processor for at-least-once public booking cloud requests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .cloud_client import BookingCloudClient
from .models import BookingCloudRequest, BookingSettings
from .schemas import PublicBookingCreate
from .service import BookingService, BookingUnavailableError

SettingsResolver = Callable[
    [AsyncSession, UUID],
    Awaitable[BookingSettings | None],
]

BookingCreator = Callable[
    [AsyncSession, BookingSettings, PublicBookingCreate],
    Awaitable[tuple[Any, Any]],
]


class BookingCloudPayloadError(ValueError):
    """Cloud request does not satisfy the local booking input contract."""


class BookingCloudProcessor:
    """Convert delivered cloud requests into authoritative local appointments."""

    def __init__(
        self,
        *,
        cloud_client: BookingCloudClient,
        settings_resolver: SettingsResolver = BookingService.get_settings_for_clinic,
        booking_creator: BookingCreator = BookingService.create_public_booking,
    ) -> None:
        self._cloud_client = cloud_client
        self._settings_resolver = settings_resolver
        self._booking_creator = booking_creator

    @staticmethod
    def _request_id(request: dict[str, Any]) -> str:
        value = request.get("request_id")

        if not isinstance(value, str) or not value.strip():
            raise BookingCloudPayloadError("Booking request ID is missing")

        return value.strip()

    @staticmethod
    def _booking_data(request: dict[str, Any]) -> PublicBookingCreate:
        patient = request.get("patient")

        if not isinstance(patient, dict):
            raise BookingCloudPayloadError("Booking patient payload is invalid")

        payload = {
            "professional_id": request.get("local_professional_id"),
            "start_time": request.get("start_time"),
            "first_name": patient.get("first_name"),
            "last_name": patient.get("last_name"),
            "phone": patient.get("phone"),
            "date_of_birth": patient.get("date_of_birth"),
            "email": patient.get("email"),
            # Cloud end_time is deliberately ignored. Local booking settings
            # remain authoritative for appointment duration.
            "reason": request.get("reason"),
        }

        try:
            return PublicBookingCreate.model_validate(payload)
        except ValidationError as exc:
            raise BookingCloudPayloadError(
                "Booking request does not satisfy the local contract"
            ) from exc

    @staticmethod
    def _result_from_receipt(
        receipt: BookingCloudRequest,
    ) -> dict[str, str] | None:
        if receipt.status == "accepted" and receipt.appointment_id is not None:
            return {
                "status": "accepted",
                "local_appointment_id": str(receipt.appointment_id),
            }

        if receipt.status == "rejected" and receipt.rejection_code:
            return {
                "status": "rejected",
                "rejection_code": receipt.rejection_code,
            }

        return None

    @staticmethod
    def _rejection_code(exc: BookingUnavailableError) -> str:
        message = str(exc).lower()

        if "disabled" in message:
            return "booking_disabled"

        if "professional" in message:
            return "professional_unavailable"

        if "clinic" in message:
            return "clinic_unavailable"

        if "slot" in message or "future" in message or "booking window" in message:
            return "slot_unavailable"

        return "booking_unavailable"

    @staticmethod
    def _reject(
        receipt: BookingCloudRequest,
        rejection_code: str,
    ) -> dict[str, str]:
        receipt.status = "rejected"
        receipt.appointment_id = None
        receipt.rejection_code = rejection_code

        return {
            "status": "rejected",
            "rejection_code": rejection_code,
        }

    async def process_request(
        self,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        request: dict[str, Any],
    ) -> dict[str, str]:
        """Process one delivered request and synchronize its durable result."""

        request_id = self._request_id(request)

        try:
            # Serialize duplicate deliveries for the same clinic/request.
            # This lock lives until commit/rollback of the local transaction.
            await db.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtext(:clinic_lock),
                        hashtext(:request_lock)
                    )
                    """
                ),
                {
                    "clinic_lock": str(clinic_id),
                    "request_lock": request_id,
                },
            )

            existing_result = await db.execute(
                select(BookingCloudRequest)
                .where(
                    BookingCloudRequest.clinic_id == clinic_id,
                    BookingCloudRequest.request_id == request_id,
                )
                .with_for_update()
            )

            receipt = existing_result.scalar_one_or_none()

            if receipt is None:
                receipt = BookingCloudRequest(
                    clinic_id=clinic_id,
                    request_id=request_id,
                    status="processing",
                )
                db.add(receipt)
                await db.flush()

            result = self._result_from_receipt(receipt)

            if result is None:
                try:
                    booking_data = self._booking_data(request)
                except BookingCloudPayloadError:
                    result = self._reject(
                        receipt,
                        "invalid_request",
                    )
                else:
                    settings = await self._settings_resolver(
                        db,
                        clinic_id,
                    )

                    if settings is None:
                        result = self._reject(
                            receipt,
                            "booking_disabled",
                        )
                    else:
                        try:
                            appointment, _ = await self._booking_creator(
                                db,
                                settings,
                                booking_data,
                            )
                        except BookingUnavailableError as exc:
                            result = self._reject(
                                receipt,
                                self._rejection_code(exc),
                            )
                        else:
                            receipt.status = "accepted"
                            receipt.appointment_id = appointment.id
                            receipt.rejection_code = None

                            result = {
                                "status": "accepted",
                                "local_appointment_id": str(appointment.id),
                            }

                await db.flush()

            # Local PostgreSQL becomes durable BEFORE informing the cloud.
            await db.commit()

        except Exception:
            await db.rollback()
            raise

        # Deliberately outside the DB transaction. If this outbound call
        # fails, the durable terminal receipt remains and the next pull can
        # replay the exact accepted/rejected result without another booking.
        await self._cloud_client.resolve_request(
            request_id,
            result,
        )

        return result
