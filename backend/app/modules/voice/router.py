"""Authenticated Dentora Voice HTTP surface.

Audio never reaches this router. The browser sends microphone audio only to the
loopback faster-whisper runtime; this surface receives transcript text and
executes deterministic plans.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.schemas import ApiResponse
from app.database import get_db

from .executor import execute_plans
from .intent import interpret
from .schemas import ExecuteResponse, InterpretRequest, InterpretResponse

router = APIRouter()

@router.post("/interpret", response_model=ApiResponse[InterpretResponse])
async def interpret_voice(
    body: InterpretRequest,
    _: Annotated[None, Depends(require_permission("voice.use"))],
) -> ApiResponse[InterpretResponse]:
    plans = interpret(body.transcript, body.context)
    clarification = any(plan.command == "UNKNOWN" or plan.confidence < 0.85 for plan in plans)
    return ApiResponse(data=InterpretResponse(
        commands=plans,
        clarification_required=clarification,
        clarification_reason="low_confidence_or_unknown" if clarification else None,
    ))

@router.post("/execute", response_model=ApiResponse[ExecuteResponse])
async def execute_voice(
    body: InterpretRequest,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: Annotated[None, Depends(require_permission("voice.use"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ExecuteResponse]:
    plans = interpret(body.transcript, body.context)
    result = await execute_plans(
        db,
        clinic_id=ctx.clinic_id,
        user_id=ctx.user_id,
        role=ctx.role,
        plans=plans,
        context=body.context,
    )
    await db.commit()
    return ApiResponse(data=result)
