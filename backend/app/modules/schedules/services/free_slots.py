"""Reusable real free-slot resolver.

Combines schedules availability with Agenda appointments so every caller
(agents, public booking, future integrations) uses the same source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agenda.service import AppointmentService

from .availability import AvailabilityService


BLOCKING_STATUSES = {
    "scheduled",
    "confirmed",
    "checked_in",
    "in_treatment",
    "completed",
}


@dataclass(frozen=True)
class FreeWindow:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def _subtract(
    start: datetime,
    end: datetime,
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Return portions of [start, end] not covered by busy intervals."""
    free = [(start, end)]

    for busy_start, busy_end in busy:
        next_free: list[tuple[datetime, datetime]] = []

        for free_start, free_end in free:
            if busy_end <= free_start or busy_start >= free_end:
                next_free.append((free_start, free_end))
                continue

            if busy_start > free_start:
                next_free.append((free_start, busy_start))

            if busy_end < free_end:
                next_free.append((busy_end, free_end))

        free = next_free

    return free


class FreeSlotService:
    @staticmethod
    async def find(
        db: AsyncSession,
        clinic_id: UUID,
        professional_id: UUID,
        start_day: date,
        end_day: date,
        *,
        min_minutes: int = 30,
    ) -> tuple[str, list[FreeWindow]]:
        """Return real free windows for a professional.

        Clinic/professional opening hours are resolved by schedules, then
        appointments in blocking states are subtracted from those windows.
        """
        tz_name, ranges = await AvailabilityService.resolve(
            db,
            clinic_id,
            start_day,
            end_day,
            professional_id,
        )

        open_ranges = sorted(
            (item.start, item.end)
            for item in ranges
            if item.state == "open"
        )

        if not open_ranges:
            return tz_name, []

        clinic_tz = ZoneInfo(tz_name)

        range_start = datetime.combine(
            start_day,
            time.min,
            tzinfo=clinic_tz,
        ).astimezone(UTC)

        range_end = datetime.combine(
            end_day,
            time.max,
            tzinfo=clinic_tz,
        ).astimezone(UTC)

        appointments, _ = await AppointmentService.list_appointments(
            db,
            clinic_id,
            start_date=range_start,
            end_date=range_end,
            professional_id=professional_id,
            page_size=500,
        )

        busy = sorted(
            (appointment.start_time, appointment.end_time)
            for appointment in appointments
            if (
                appointment.status in BLOCKING_STATUSES
                and appointment.start_time
                and appointment.end_time
            )
        )

        minimum_duration = timedelta(minutes=min_minutes)
        windows: list[FreeWindow] = []

        for open_start, open_end in open_ranges:
            for free_start, free_end in _subtract(open_start, open_end, busy):
                if free_end - free_start < minimum_duration:
                    continue

                windows.append(
                    FreeWindow(
                        start=free_start.astimezone(clinic_tz),
                        end=free_end.astimezone(clinic_tz),
                    )
                )

        windows.sort(key=lambda item: item.start)
        return tz_name, windows
