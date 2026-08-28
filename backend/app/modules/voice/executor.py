"""Validated sequential Voice execution over the existing ToolRegistry."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.context import AgentContext, AgentMode
from app.core.agents.models import Agent
from app.core.agents.service import AgentService
from app.core.agents.tools import tool_registry
from app.core.auth.permissions import get_role_permissions

from .intent import confidence_requires_clarification
from .privacy import sanitize_audit_payload
from .registry import BY_NAME
from .schemas import (
    ExecuteResponse,
    VoiceCommandPlan,
    VoiceState,
    VoiceStepResult,
    VoiceUIAction,
    VoiceUIContext,
)

async def _get_agent(db: AsyncSession, clinic_id: UUID) -> Agent:
    agent = await db.scalar(select(Agent).where(
        Agent.clinic_id == clinic_id, Agent.type == "voice"
    ).limit(1))
    if agent is None:
        agent = await AgentService.create_agent(
            db, clinic_id, name="Dentora Voice", type="voice", mode="autonomous"
        )
    return agent

async def _build_ctx(db: AsyncSession, *, clinic_id: UUID, user_id: UUID, role: str) -> AgentContext:
    agent = await _get_agent(db, clinic_id)
    session = await AgentService.start_session(
        db,
        agent_id=agent.id,
        clinic_id=clinic_id,
        supervisor_id=user_id,
        metadata={"surface": "voice"},
    )
    return AgentContext(
        agent_id=agent.id,
        session_id=session.id,
        clinic_id=clinic_id,
        mode=AgentMode.AUTONOMOUS,
        permissions=get_role_permissions(role),
        tools=tool_registry,
        db=db,
        supervisor_id=user_id,
        metadata={"surface": "voice"},
        audit_sanitizer=sanitize_audit_payload,
    )

async def _call(ctx: AgentContext, name: str, args: dict[str, Any]):
    return await ctx.tools.call(ctx, name, args)

async def _resolve_patient(ctx: AgentContext, plan: VoiceCommandPlan, ui: VoiceUIContext):
    name = plan.entities.get("patient_name")
    if not name and ui.patient_id:
        return str(ui.patient_id), None
    if not name:
        return None, VoiceStepResult(
            command=plan.command,
            ok=False,
            confidence=plan.confidence,
            message="patient_context_required",
            clarification_required=True,
        )
    result = await _call(ctx, "patients.search_patients", {"query": name, "limit": 10})
    if not result.ok:
        return None, VoiceStepResult(
            command=plan.command, ok=False, confidence=plan.confidence, message=result.error
        )
    payload = result.data or {}
    patients = payload.get("patients", [])
    if len(patients) == 0:
        return None, VoiceStepResult(
            command=plan.command,
            ok=False,
            confidence=plan.confidence,
            message="patient_not_found",
        )
    if len(patients) > 1:
        candidates = [
            {"id": str(item.get("id")), "full_name": item.get("full_name")}
            for item in patients[:5]
        ]
        return None, VoiceStepResult(
            command=plan.command,
            ok=False,
            confidence=plan.confidence,
            message="ambiguous_patient",
            data={"candidates": candidates},
            clarification_required=True,
        )
    return str(patients[0]["id"]), None

async def _ui(ctx: AgentContext, action: str, payload: dict[str, Any]):
    result = await _call(ctx, "voice.ui_action", {"action": action, "payload": payload})
    if not result.ok:
        return None, result.error
    data = result.data or {}
    return VoiceUIAction(action=data["action"], payload=data.get("payload", {})), None

async def execute_plans(
    db: AsyncSession,
    *,
    clinic_id: UUID,
    user_id: UUID,
    role: str,
    plans: list[VoiceCommandPlan],
    context: VoiceUIContext,
) -> ExecuteResponse:
    ctx = await _build_ctx(db, clinic_id=clinic_id, user_id=user_id, role=role)
    ui = context.model_copy(deep=True)
    steps: list[VoiceStepResult] = []

    for plan in plans:
        if not plan.available:
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message=plan.blocked_reason or "integration_unavailable",
            ))
            break
        if confidence_requires_clarification(plan):
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message="clarification_required",
                clarification_required=True,
                confirmation_required=plan.requires_confirmation,
            ))
            break

        spec = BY_NAME.get(plan.command)
        if spec is None:
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message="unknown_command",
            ))
            break

        if plan.command.startswith("GO_TO_"):
            action, error = await _ui(ctx, "navigate", {"route": spec.target})
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=action is not None,
                confidence=plan.confidence,
                message=error,
                ui_action=action,
            ))
            if action is None:
                break
            ui.route = str(spec.target)
            continue

        if plan.command in {"OPEN_PATIENT", "SEARCH_PATIENT"}:
            patient_id, failure = await _resolve_patient(ctx, plan, ui)
            if failure:
                steps.append(failure)
                break
            if plan.command == "SEARCH_PATIENT":
                action, error = await _ui(ctx, "navigate", {
                    "route": "/patients",
                    "search": plan.entities.get("patient_name", ""),
                })
            else:
                route = f"/patients/{patient_id}"
                action, error = await _ui(ctx, "navigate", {"route": route})
                ui.patient_id = UUID(patient_id)
                ui.route = route
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=action is not None,
                confidence=plan.confidence,
                message=error,
                ui_action=action,
            ))
            if action is None:
                break
            continue

        patient_id, failure = await _resolve_patient(ctx, plan, ui)
        if failure:
            steps.append(failure)
            break

        scene_result = await _call(ctx, "dental_3d.get_patient_scene", {"patient_id": patient_id})
        if not scene_result.ok:
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message=scene_result.error,
            ))
            break
        scene = scene_result.data or {}
        if scene.get("error"):
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message=str(scene["error"]),
            ))
            break

        action_name = {
            "OPEN_CBCT": "open_cbct",
            "SHOW_3D": "show_3d",
            "SHOW_TOOTH_SEGMENTATION": "show_tooth_segmentation",
            "SHOW_NERVE": "show_nerve",
            "OPEN_IMPLANT_PLANNER": "open_implant_planner",
        }.get(plan.command)
        if action_name is None:
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message="integration_unavailable",
            ))
            break

        if plan.command == "OPEN_CBCT" and not scene.get("cbct_series"):
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message="cbct_not_available",
            ))
            break
        if plan.command == "SHOW_TOOTH_SEGMENTATION" and (
            scene.get("segmentation") or {}
        ).get("status") == "not_available":
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message="segmentation_not_available",
            ))
            break
        if plan.command == "SHOW_NERVE" and (
            scene.get("nerve_detection") or {}
        ).get("status") in {None, "not_available", "failed"}:
            steps.append(VoiceStepResult(
                command=plan.command,
                ok=False,
                confidence=plan.confidence,
                message="nerve_not_available",
            ))
            break

        route = f"/patients/{patient_id}"
        payload: dict[str, Any] = {"patient_id": patient_id, "route": route}
        if plan.command == "OPEN_CBCT":
            series = scene["cbct_series"][-1]
            payload["study"] = str(
                series.get("series_instance_uid") or series.get("seriesInstanceUid") or ""
            )
            ui.current_study = payload["study"] or None
        action, error = await _ui(ctx, action_name, payload)
        steps.append(VoiceStepResult(
            command=plan.command,
            ok=action is not None,
            confidence=plan.confidence,
            message=error,
            ui_action=action,
        ))
        if action is None:
            break
        ui.patient_id = UUID(patient_id)
        ui.route = route
        ui.viewer_open = True

    if not steps:
        state = VoiceState.ERROR
    elif steps[-1].clarification_required:
        state = VoiceState.CLARIFICATION_REQUIRED
    elif steps[-1].confirmation_required:
        state = VoiceState.CONFIRMATION_REQUIRED
    elif all(step.ok for step in steps):
        state = VoiceState.SUCCESS
    else:
        state = VoiceState.ERROR
    return ExecuteResponse(state=state, steps=steps, context=ui)
