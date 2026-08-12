"""Agent tools for the schedules module.

Thin wrappers over ``AvailabilityService`` — no business logic here.
Clinic-scoped; RBAC via the existing ``schedules.availability.read``.

``get_availability`` returns the clinic's open working windows for a day.
``find_free_slots`` goes further: it subtracts the professional's booked
appointments from those windows and returns discrete bookable slots
(this is allowed to read agenda because ``agenda`` is in
``manifest.depends``). See
``docs/technical/copilot-agentic-architecture.md`` §3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_cls
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.agents import AgentContext, Tool, ToolCategory

from .services.availability import AvailabilityService
from .services.free_slots import FreeSlotService, _subtract as _subtract


class AvailabilityArgs(BaseModel):
    date: date_cls = Field(description="Día a consultar (YYYY-MM-DD).")
    professional_id: UUID | None = Field(
        default=None, description="Opcional: restringe a un profesional."
    )


class FreeSlotsArgs(BaseModel):
    professional_id: UUID
    slot_minutes: int = Field(
        default=30,
        ge=5,
        le=480,
        description="Duración mínima (min) que debe caber en la ventana libre para incluirla.",
    )
    days_ahead: int = Field(default=14, ge=1, le=60)
    part_of_day: Literal["morning", "afternoon", "any"] = "any"
    date_from: date_cls | None = Field(
        default=None, description="Primer día a considerar; por defecto hoy."
    )
    limit: int = Field(default=5, ge=1, le=20)


async def _get_availability(ctx: AgentContext, params: AvailabilityArgs) -> dict:
    tz_name, ranges = await AvailabilityService.resolve(
        ctx.db, ctx.clinic_id, params.date, params.date, params.professional_id
    )
    open_windows = [{"start": r.start, "end": r.end} for r in ranges if r.state == "open"]
    return {"date": params.date, "timezone": tz_name, "open_windows": open_windows}


def _overlaps_part(local_start: datetime, local_end: datetime, part: str) -> bool:
    """Whether a free window overlaps the requested part of the day (split at 14:00)."""
    if part == "morning":
        return local_start.hour < 14
    if part == "afternoon":
        noon = local_start.replace(hour=14, minute=0, second=0, microsecond=0)
        return local_end > noon
    return True


async def _find_free_slots(ctx: AgentContext, params: FreeSlotsArgs) -> dict:
    start_day = params.date_from or datetime.now(UTC).date()
    end_day = start_day + timedelta(days=params.days_ahead)

    _tz_name, free_windows = await FreeSlotService.find(
        ctx.db,
        ctx.clinic_id,
        params.professional_id,
        start_day,
        end_day,
        min_minutes=params.slot_minutes,
    )

    windows = [
        window
        for window in free_windows
        if _overlaps_part(window.start, window.end, params.part_of_day)
    ]

    return {
        "professional_id": params.professional_id,
        "min_minutes": params.slot_minutes,
        "free_windows": [
            {
                "start": window.start,
                "end": window.end,
                "minutes": window.minutes,
            }
            for window in windows[: params.limit]
        ],
    }


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="get_availability",
            description=(
                "Ventanas de horario abierto de la clínica (o de un profesional) para un día. "
                "No descuenta citas reservadas; usa find_free_slots para huecos reales."
            ),
            parameters=AvailabilityArgs,
            handler=_get_availability,
            permissions=["schedules.availability.read"],
            category=ToolCategory.READ,
        ),
        Tool(
            name="find_free_slots",
            description=(
                "Ventanas libres reales de un profesional (horario abierto menos citas ya "
                "reservadas), ordenadas de la más cercana a la más lejana. Devuelve "
                "`free_windows` con `start`, `end` y `minutes` (la duración real de cada hueco "
                "contiguo), no slots de tamaño fijo: úsalo para saber cuánto dura cada hueco y "
                "proponer una hora dentro. `slot_minutes` filtra ventanas que no llegan a esa "
                "duración mínima. Filtra también por franja (part_of_day) y días (days_ahead)."
            ),
            parameters=FreeSlotsArgs,
            handler=_find_free_slots,
            permissions=["schedules.availability.read", "agenda.appointments.read"],
            category=ToolCategory.READ,
        ),
    ]
