"""Read-only treatment progress intelligence.

This endpoint intentionally derives operational progress from authoritative
TreatmentPlan / PlannedTreatmentItem / session state. It does not mutate the
plan, diagnose a patient, predict a clinical outcome, or recommend treatment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .models import TreatmentPlan
from .service import TreatmentPlanService

router = APIRouter()


class ProgressBreakdown(BaseModel):
    """Status counts and completion percentage for one progress level."""

    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    pending: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    completion_percent: float = Field(ge=0, le=100)


class TreatmentProgressIntelligence(BaseModel):
    """Deterministic, non-clinical progress view for a treatment plan."""

    plan_id: UUID
    plan_status: str
    items: ProgressBreakdown
    sessions: ProgressBreakdown
    first_pending_item_id: UUID | None = None
    last_completed_at: datetime | None = None
    days_since_last_completion: int | None = Field(default=None, ge=0)
    next_appointment_at: datetime | None = None
    operational_state: str
    generated_at: datetime


def _breakdown(rows: list[object]) -> ProgressBreakdown:
    statuses = [getattr(row, "status", None) for row in rows]
    completed = statuses.count("completed")
    pending = statuses.count("pending")
    cancelled = statuses.count("cancelled")
    actionable = completed + pending
    percent = round((completed * 100.0 / actionable), 1) if actionable else 0.0
    return ProgressBreakdown(
        total=len(rows),
        completed=completed,
        pending=pending,
        cancelled=cancelled,
        completion_percent=percent,
    )


def build_progress_intelligence(
    plan: TreatmentPlan,
    *,
    next_appointment_at: datetime | None,
    now: datetime | None = None,
) -> TreatmentProgressIntelligence:
    """Build a stable progress snapshot from an already-loaded plan.

    ``cancelled`` rows are reported but excluded from the completion-rate
    denominator because they are no longer actionable work.
    """
    generated_at = now or datetime.now(UTC)
    items = list(plan.items or [])
    sessions = [session for item in items for session in (item.sessions or [])]
    item_breakdown = _breakdown(items)
    session_breakdown = _breakdown(sessions)

    pending_items = sorted(
        (item for item in items if item.status == "pending"),
        key=lambda item: (item.sequence_order, str(item.id)),
    )
    first_pending_item_id = pending_items[0].id if pending_items else None

    completed_times = [
        completed_at
        for completed_at in (
            [item.completed_at for item in items] + [session.completed_at for session in sessions]
        )
        if completed_at is not None
    ]
    last_completed_at = max(completed_times) if completed_times else None
    days_since_last_completion = None
    if last_completed_at is not None:
        anchor = last_completed_at
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        days_since_last_completion = max((generated_at - anchor).days, 0)

    if plan.status == "closed":
        operational_state = "closed"
    elif plan.status in {"completed", "archived"}:
        operational_state = "completed"
    elif item_breakdown.total == 0:
        operational_state = "not_started"
    elif item_breakdown.pending == 0 and item_breakdown.completed > 0:
        operational_state = "completed"
    elif item_breakdown.completed == 0 and session_breakdown.completed == 0:
        operational_state = "not_started"
    elif plan.status == "active" and next_appointment_at is None:
        operational_state = "needs_scheduling"
    else:
        operational_state = "in_progress"

    return TreatmentProgressIntelligence(
        plan_id=plan.id,
        plan_status=plan.status,
        items=item_breakdown,
        sessions=session_breakdown,
        first_pending_item_id=first_pending_item_id,
        last_completed_at=last_completed_at,
        days_since_last_completion=days_since_last_completion,
        next_appointment_at=next_appointment_at,
        operational_state=operational_state,
        generated_at=generated_at,
    )


async def get_progress_intelligence(
    db: AsyncSession,
    clinic_id: UUID,
    plan_id: UUID,
) -> TreatmentProgressIntelligence | None:
    """Load a clinic-scoped plan and derive its read-only progress snapshot."""
    plan = await TreatmentPlanService.get(db, clinic_id, plan_id)
    if plan is None:
        return None

    # Appointment links are already an allowed dependency of treatment_plan.
    # Keep the same association path used by list_pipeline so this remains a
    # single bounded query and cannot cross clinic boundaries.
    next_result = await db.execute(
        sa_text(
            """
            SELECT MIN(a.start_time)
            FROM planned_treatment_items pti
            JOIN appointment_treatments atx ON atx.planned_treatment_item_id = pti.id
            JOIN appointments a ON a.id = atx.appointment_id
            WHERE pti.treatment_plan_id = :plan_id
              AND pti.clinic_id = :clinic_id
              AND a.start_time >= NOW()
              AND a.status NOT IN ('cancelled', 'no_show')
            """
        ),
        {"plan_id": plan_id, "clinic_id": clinic_id},
    )
    next_appointment_at = next_result.scalar_one_or_none()
    return build_progress_intelligence(plan, next_appointment_at=next_appointment_at)


@router.get(
    "/treatment-plans/{plan_id}/progress-intelligence",
    response_model=ApiResponse[TreatmentProgressIntelligence],
)
async def treatment_progress_intelligence(
    plan_id: UUID,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("treatment_plan.plans.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TreatmentProgressIntelligence]:
    """Return deterministic operational progress for one treatment plan."""
    snapshot = await get_progress_intelligence(db, ctx.clinic_id, plan_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Treatment plan not found")
    return ApiResponse(data=snapshot)
