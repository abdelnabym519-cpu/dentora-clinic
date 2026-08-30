"""Deterministic clinical-context assembly for patient-scoped AI.

This builds the *input* for the clinical AI features (case summary,
clinical report, second review, AI treatment suggestions, case
intelligence). It NEVER invokes a model and NEVER invents data: it only
reads what the caller is allowed to read through the same agent-tool
chokepoint the copilot uses. Every read:

* is clinic-scoped (``ctx.clinic_id``) — no cross-tenant data;
* is RBAC-checked against the caller's role — no section the caller
  could not open in the UI is included;
* returns structured data (no free-text PHI the redactor can't tokenize),
  matching the privacy posture of ``docs/technical/copilot-agentic-architecture.md``.

The gathered dict is rendered into a prompt by :mod:`app.modules.copilot.clinical`
and tokenized by the existing :class:`~app.core.agents.redaction.Redactor`
before it leaves the server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.context import AgentContext, AgentMode
from app.core.agents.service import AgentService
from app.core.agents.tools.registry import tool_registry

from .bridge import COPILOT_GUARDRAILS


class PatientNotFoundError(Exception):
    """The patient does not exist in the caller's clinic (or no access)."""


@dataclass
class ClinicalContext:
    """The privacy-scoped, structured view of one patient's case."""

    clinic_id: UUID
    patient_id: UUID
    role: str
    patient: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    appointments: list[dict[str, Any]] = field(default_factory=list)
    budgets: list[dict[str, Any]] = field(default_factory=list)
    invoices: list[dict[str, Any]] = field(default_factory=list)
    payments: dict[str, Any] = field(default_factory=dict)
    recalls: list[dict[str, Any]] = field(default_factory=list)
    # Human-readable provenance, e.g. ["patients.get_patient", ...]
    sources: list[str] = field(default_factory=list)
    # Sections the caller's role could not access (for transparency).
    access_denied: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.patient or self.patient.get("error") == "not_found"


async def _call(
    db: AsyncSession,
    ctx: AgentContext,
    name: str,
    args: dict[str, Any],
    *,
    denied: list[str],
    sources: list[str],
) -> Any | None:
    """Invoke a registry tool through the RBAC/clinic-scoped chokepoint.

    Returns the tool's data payload, or ``None`` when the module/tool is
    unavailable or the caller lacks permission (recorded transparently).
    """
    if name not in tool_registry.list():
        return None  # module uninstalled
    # The registry enforces clinic scope (clinic_id) and RBAC
    # (ctx.permissions) itself; a not-ok result means "denied/missing" and
    # the section is omitted + recorded for transparency. Each call runs
    # in a SAVEPOINT so an argument/validation error (and the audit-log
    # write the registry performs) cannot poison the whole request
    # transaction or abort the remaining sections.
    try:
        async with db.begin_nested():
            res = await tool_registry.call(ctx, name, args)
            if not res.ok:
                raise _ToolDeniedError
    except _ToolDeniedError:
        denied.append(name)
        return None
    except Exception:  # invalid args / unsupported filter for this tool
        denied.append(name)
        return None
    sources.append(name)
    return res.data


class _ToolDeniedError(Exception):
    """Internal: a tool returned a not-ok (denied/not-found) result."""


async def build_clinical_context(
    db: AsyncSession,
    *,
    clinic_id: UUID,
    user_id: UUID,
    role: str,
    permissions: list[str],
    patient_id: UUID,
    today: date | None = None,
) -> ClinicalContext:
    """Read the patient's case through the agent-tool registry."""
    from app.core.auth.permissions import get_role_permissions

    today = today or date.today()

    agent = await AgentService.create_agent(
        db, clinic_id=clinic_id, name="Copilot clinical AI", type="copilot", mode="autonomous"
    )
    session = await AgentService.start_session(
        db,
        agent_id=agent.id,
        clinic_id=clinic_id,
        supervisor_id=user_id,
        metadata={"surface": "copilot_clinical_ai"},
    )
    ctx = AgentContext(
        agent_id=agent.id,
        session_id=session.id,
        clinic_id=clinic_id,
        mode=AgentMode.AUTONOMOUS,
        permissions=permissions or get_role_permissions(role),
        tools=tool_registry,
        db=db,
        supervisor_id=user_id,
        guardrail_config=COPILOT_GUARDRAILS,
        metadata={"surface": "copilot_clinical_ai", "patient_id": str(patient_id)},
    )

    cc = ClinicalContext(clinic_id=clinic_id, patient_id=patient_id, role=role)
    denied: list[str] = []

    # 1) Identity / ownership — authoritative gate.
    patient = await _call(
        db,
        ctx,
        "patients.get_patient",
        {"patient_id": patient_id},
        denied=denied,
        sources=cc.sources,
    )
    if patient is None or patient.get("error") == "not_found":
        raise PatientNotFoundError(str(patient_id))
    cc.patient = patient

    # 2) Recent clinical/administrative activity (events only, no prose).
    tl = await _call(
        db,
        ctx,
        "patient_timeline.get_patient_timeline",
        {"patient_id": patient_id, "limit": 40},
        denied=denied,
        sources=cc.sources,
    )
    if tl:
        cc.timeline = tl.get("events", [])

    # 3) Appointments: day overview over a wide window around today is
    #    clinic-wide, so instead pull the patient's activity from the
    #    timeline event types plus budgets/invoices/payments/recalls.
    budgets = await _call(
        db,
        ctx,
        "budget.list_budgets",
        {"patient_id": patient_id},
        denied=denied,
        sources=cc.sources,
    )
    if budgets:
        cc.budgets = budgets.get("budgets", [])

    invoices = await _call(
        db,
        ctx,
        "billing.list_invoices",
        {"patient_id": patient_id},
        denied=denied,
        sources=cc.sources,
    )
    if invoices:
        # list_invoices returns {"invoices": [...]} or a list depending on tool.
        cc.invoices = invoices.get("invoices", invoices if isinstance(invoices, list) else [])

    payments = await _call(
        db,
        ctx,
        "payments.patient_payment_history",
        {"patient_id": patient_id},
        denied=denied,
        sources=cc.sources,
    )
    if payments:
        cc.payments = payments

    recalls = await _call(
        db,
        ctx,
        "recalls.list_due_recalls",
        {"patient_id": patient_id},
        denied=denied,
        sources=cc.sources,
    )
    if recalls:
        cc.recalls = recalls.get("recalls", [])

    # Appointments specifically for this patient are best-effort derived
    # from timeline events of type appointment (kept structured).
    cc.appointments = [
        e for e in cc.timeline if "appointment" in str(e.get("event_type", "")).lower()
    ]

    cc.access_denied = sorted(set(denied))
    cc.sources = sorted(set(cc.sources))
    return cc


def render_context_for_prompt(cc: ClinicalContext) -> str:
    """Serialize the structured context into a compact, token-safe block."""
    payload = {
        "patient": {
            k: v
            for k, v in cc.patient.items()
            # PII (name/phone/email) is tokenized by the redactor; keep id
            # and clinical-status fields here.
            if k in ("id", "status", "date_of_birth", "do_not_contact", "full_name")
        },
        "recent_events": [
            {
                "type": e.get("event_type"),
                "category": e.get("category"),
                "title": e.get("title"),
                "at": str(e.get("occurred_at")),
            }
            for e in cc.timeline
        ],
        "budgets": cc.budgets,
        "invoices": cc.invoices,
        "payments_summary": cc.payments,
        "recalls": cc.recalls,
        "sources": cc.sources,
        "sections_not_accessible": cc.access_denied,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
