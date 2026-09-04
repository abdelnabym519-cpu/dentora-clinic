"""Business logic for public online booking."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic, ClinicMembership, User
from app.modules.agenda.models import Appointment
from app.modules.agenda.service import AppointmentService
from app.modules.patients.composition import build_patient_service
from app.modules.patients.models import Patient
from app.modules.schedules.services.free_slots import FreeSlotService

from .models import BookingSettings
from .schemas import PublicBookingCreate

_ACTIVE_APPOINTMENT_STATUSES = {
    "scheduled",
    "confirmed",
    "checked_in",
    "in_treatment",
}


class BookingUnavailableError(ValueError):
    """Requested booking cannot be created."""


def _normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value if ch.isdigit())


def _clinic_local(value: datetime, tz: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


class BookingService:
    @staticmethod
    async def get_settings_by_slug(
        db: AsyncSession,
        slug: str,
    ) -> BookingSettings | None:
        result = await db.execute(
            select(BookingSettings).where(
                BookingSettings.public_slug == slug,
                BookingSettings.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_settings_for_clinic(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> BookingSettings | None:
        result = await db.execute(
            select(BookingSettings).where(BookingSettings.clinic_id == clinic_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_clinic(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> Clinic | None:
        result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def list_public_professionals(
        db: AsyncSession,
        clinic_id: UUID,
    ) -> list[User]:
        result = await db.execute(
            select(User)
            .join(
                ClinicMembership,
                ClinicMembership.user_id == User.id,
            )
            .where(
                ClinicMembership.clinic_id == clinic_id,
                ClinicMembership.is_professional.is_(True),
                User.is_active.is_(True),
            )
            .order_by(User.first_name, User.last_name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_professional(
        db: AsyncSession,
        clinic_id: UUID,
        professional_id: UUID,
    ) -> User | None:
        result = await db.execute(
            select(User)
            .join(
                ClinicMembership,
                ClinicMembership.user_id == User.id,
            )
            .where(
                User.id == professional_id,
                ClinicMembership.clinic_id == clinic_id,
                ClinicMembership.is_professional.is_(True),
                User.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_bookable_slots(
        db: AsyncSession,
        settings: BookingSettings,
        professional_id: UUID,
        day: date,
    ) -> tuple[str, list[tuple[datetime, datetime]]]:
        clinic = await BookingService.get_clinic(db, settings.clinic_id)
        if clinic is None:
            raise BookingUnavailableError("Clinic not found")

        tz = ZoneInfo(clinic.timezone)
        now = datetime.now(tz)
        today = now.date()
        latest = today + timedelta(days=settings.days_ahead)

        if day < today or day > latest:
            return clinic.timezone, []

        professional = await BookingService.get_professional(
            db,
            settings.clinic_id,
            professional_id,
        )
        if professional is None:
            return clinic.timezone, []

        tz_name, windows = await FreeSlotService.find(
            db,
            settings.clinic_id,
            professional_id,
            day,
            day,
            min_minutes=settings.slot_minutes,
        )

        duration = timedelta(minutes=settings.slot_minutes)
        slots: list[tuple[datetime, datetime]] = []

        for window in windows:
            cursor = window.start

            while cursor + duration <= window.end:
                slot_end = cursor + duration

                if cursor > now:
                    slots.append((cursor, slot_end))

                cursor += duration

        return tz_name, slots

    @staticmethod
    async def _match_patient(
        db: AsyncSession,
        clinic_id: UUID,
        data: PublicBookingCreate,
    ) -> Patient | None:
        """Match only when identity evidence is strong and unambiguous."""

        first_name = data.first_name.strip()
        last_name = data.last_name.strip()
        wanted_phone = _normalize_phone(data.phone)

        result = await db.execute(
            select(Patient).where(
                Patient.clinic_id == clinic_id,
                Patient.status != "archived",
                func.lower(Patient.first_name) == first_name.lower(),
                func.lower(Patient.last_name) == last_name.lower(),
                Patient.date_of_birth == data.date_of_birth,
            )
        )

        candidates = [
            patient
            for patient in result.scalars().all()
            if _normalize_phone(patient.phone) == wanted_phone
        ]

        if len(candidates) == 1:
            return candidates[0]

        if len(candidates) > 1 and data.email:
            wanted_email = str(data.email).strip().lower()

            email_matches = [
                patient
                for patient in candidates
                if patient.email and patient.email.strip().lower() == wanted_email
            ]

            if len(email_matches) == 1:
                return email_matches[0]

        return None

    @staticmethod
    async def _get_or_create_patient(
        db: AsyncSession,
        clinic_id: UUID,
        data: PublicBookingCreate,
    ) -> Patient:
        patient = await BookingService._match_patient(
            db,
            clinic_id,
            data,
        )

        if patient is not None:
            return patient

        return await build_patient_service(db).create_patient(
            clinic_id,
            {
                "first_name": data.first_name.strip(),
                "last_name": data.last_name.strip(),
                "phone": data.phone.strip(),
                "email": str(data.email).strip().lower() if data.email else None,
                "date_of_birth": data.date_of_birth,
                "preferred_language": "ar",
            },
        )

    @staticmethod
    async def create_public_booking(
        db: AsyncSession,
        settings: BookingSettings,
        data: PublicBookingCreate,
    ) -> tuple[Appointment, User]:
        if not settings.enabled:
            raise BookingUnavailableError("Online booking is disabled")

        clinic = await BookingService.get_clinic(
            db,
            settings.clinic_id,
        )
        if clinic is None:
            raise BookingUnavailableError("Clinic not found")

        professional = await BookingService.get_professional(
            db,
            settings.clinic_id,
            data.professional_id,
        )
        if professional is None:
            raise BookingUnavailableError("Professional not available")

        tz = ZoneInfo(clinic.timezone)
        start_local = _clinic_local(data.start_time, tz)
        now = datetime.now(tz)

        if start_local <= now:
            raise BookingUnavailableError("Appointment must be in the future")

        latest_day = now.date() + timedelta(days=settings.days_ahead)
        if start_local.date() > latest_day:
            raise BookingUnavailableError("Appointment is outside booking window")

        duration = timedelta(minutes=settings.slot_minutes)
        start_utc = start_local.astimezone(UTC)
        end_utc = start_utc + duration
        end_local = end_utc.astimezone(tz)

        # Serialize public booking attempts for the same professional.
        # The lock lasts until the current DB transaction ends.
        await db.execute(
            text(
                """
                SELECT pg_advisory_xact_lock(
                    hashtext(:clinic_lock),
                    hashtext(:professional_lock)
                )
                """
            ),
            {
                "clinic_lock": str(settings.clinic_id),
                "professional_lock": str(data.professional_id),
            },
        )

        # Recalculate availability AFTER acquiring the lock.
        _, available_slots = await BookingService.get_bookable_slots(
            db,
            settings,
            data.professional_id,
            start_local.date(),
        )

        exact_slot_available = any(
            slot_start == start_local and slot_end == end_local
            for slot_start, slot_end in available_slots
        )

        if not exact_slot_available:
            raise BookingUnavailableError("Selected slot is no longer available")

        # Defensive backend overlap check. Do not rely on the agenda's
        # start-time unique index: online bookings normally have no cabinet.
        overlap = await db.execute(
            select(Appointment.id)
            .where(
                Appointment.clinic_id == settings.clinic_id,
                Appointment.professional_id == data.professional_id,
                Appointment.status.in_(_ACTIVE_APPOINTMENT_STATUSES),
                Appointment.start_time < end_utc,
                Appointment.end_time > start_utc,
            )
            .limit(1)
        )

        if overlap.scalar_one_or_none() is not None:
            raise BookingUnavailableError("Selected slot is no longer available")

        patient = await BookingService._get_or_create_patient(
            db,
            settings.clinic_id,
            data,
        )

        appointment = await AppointmentService.create_appointment(
            db,
            settings.clinic_id,
            {
                "patient_id": patient.id,
                "professional_id": data.professional_id,
                "start_time": start_utc,
                "end_time": end_utc,
                "treatment_type": (
                    data.reason.strip()[:100]
                    if data.reason and data.reason.strip()
                    else "Online booking"
                ),
            },
            created_by=None,
        )

        return appointment, professional
