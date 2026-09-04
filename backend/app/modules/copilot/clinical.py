"""Real-LLM patient-scoped clinical AI features.

This is the execution path shared by:

* AI Case Summary        (:func:`generate_case_summary`)
* AI Clinical Report     (:func:`generate_clinical_report`)
* AI Second Review       (:func:`generate_second_review`)
* AI Treatment Planning  (:func:`generate_treatment_suggestions`)
* Case Intelligence      (:func:`generate_case_intelligence`)

It reuses the **existing** AI architecture end to end:

    feature router
      -> :func:`build_clinical_context` (RBAC + clinic-scoped tool reads)
      -> :class:`~app.core.agents.redaction.Redactor` (PII tokenisation)
      -> :func:`app.core.llm.factory.get_provider` (the real Provider)
      -> provider.complete(...) (real streaming inference)
      -> Pydantic structured-output validation
      -> rehydration + response

There is no hard-coded clinical text and no fake fallback: if the
provider is unconfigured, unreachable, times out, or returns something
that fails schema validation, the caller gets an explicit error and the
feature reports ``AI_UNAVAILABLE`` / validation failure — never a
fabricated result.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.agents.redaction import Redactor
from app.core.llm.base import (
    Done,
    LLMConfigError,
    LLMError,
    ProviderMessage,
    Role,
    TextBlock,
    TextDelta,
    Usage,
)
from app.core.llm.factory import get_default_model, get_provider
from app.modules.copilot.models import CopilotSettings

from .clinical_context import ClinicalContext, build_clinical_context, render_context_for_prompt
from .clinical_schemas import (
    CaseIntelligence,
    CaseSummary,
    ClinicalReport,
    DeterministicSignal,
    SecondReview,
    TreatmentPlanAI,
)
from .service import CopilotSettingsService

logger = logging.getLogger(__name__)


class ClinicalAIError(Exception):
    """Raised so the router can surface a clean, non-fabricated error."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class ClinicalAIValidationError(ClinicalAIError):
    """The model returned something we could not validate into the schema."""


# --- settings / provider resolution ------------------------------------


async def _resolve_provider_and_model(db: AsyncSession, clinic_id: UUID) -> tuple[Any, str, bool]:
    """Return (provider, model, redaction_enabled) for the clinic.

    Raises :class:`ClinicalAIError` when no provider/credential is
    configured, mirroring the SSE chat fail-safe behaviour.
    """
    settings_row: CopilotSettings = await CopilotSettingsService.get_or_create(db, clinic_id)
    provider_name = settings_row.provider or settings.COPILOT_PROVIDER_DEFAULT
    model = settings_row.model or get_default_model(provider_name)
    try:
        provider = get_provider(provider_name)
    except LLMConfigError as exc:
        raise ClinicalAIError("AI_UNAVAILABLE", str(exc)) from exc
    return provider, model, bool(settings_row.redaction_enabled)


# --- low-level completion ----------------------------------------------


def _json_schema_hint(model_cls: type) -> str:
    """Tiny, prompt-friendly description of required JSON keys (no deps)."""
    fields = []
    for name, f in model_cls.model_fields.items():
        if name in ("generated_by", "model", "disclaimer"):
            continue
        ann = f.annotation
        fields.append(f'  "{name}": <{_describe(ann)}>')
    return "\n".join(fields)


def _describe(ann: Any) -> str:
    s = str(ann)
    if "list" in s.lower():
        return "array"
    if "int" in s.lower():
        return "number"
    if "bool" in s.lower():
        return "boolean"
    return "string"


async def _complete_json(
    *,
    provider: Any,
    model: str,
    system: str,
    user: str,
    result_cls: type,
    redactor: Redactor,
) -> tuple[dict[str, Any], int, int]:
    """Run one non-streaming (accumulated) JSON completion.

    Uses the real streaming Provider protocol but buffers the text, then
    extracts and validates a single JSON object. Returns
    ``(parsed_json, input_tokens, output_tokens)``.
    """
    schema_hint = _json_schema_hint(result_cls)
    full_system = (
        f"{system}\n\n"
        "You MUST answer with a single valid JSON object and nothing else "
        "(no markdown, no prose before/after). Use exactly these keys; use "
        "empty arrays/strings when there is no data; never invent patient "
        "facts that are not present in the provided context.\n"
        f"JSON shape:\n{{\n{schema_hint}\n}}"
    )

    history = [ProviderMessage(role=Role.USER, content=[TextBlock(user)])]
    # Redact PII on the way out (identity fields are tokenised).
    outgoing = redactor.redact_outgoing(history)

    text_parts: list[str] = []
    in_tokens = out_tokens = 0
    try:
        async for ev in provider.complete(
            system=full_system,
            messages=outgoing,
            tools=[],
            model=model,
            max_tokens=settings.COPILOT_MAX_TOKENS,
        ):
            if isinstance(ev, TextDelta):
                text_parts.append(ev.text)
            elif isinstance(ev, Usage):
                in_tokens, out_tokens = ev.input_tokens, ev.output_tokens
            elif isinstance(ev, Done):
                pass
    except LLMConfigError as exc:
        raise ClinicalAIError("AI_UNAVAILABLE", str(exc)) from exc
    except LLMError as exc:
        raise ClinicalAIError("AI_UNAVAILABLE", f"AI provider error: {exc}") from exc
    except Exception as exc:  # timeouts, connection, upstream HTTP errors
        raise ClinicalAIError("AI_UNAVAILABLE", f"AI request failed: {exc}") from exc

    raw = redactor.rehydrate("".join(text_parts)).strip()
    parsed = _extract_json(raw)
    if parsed is None:
        logger.warning("clinical AI: unparseable response for %s", result_cls.__name__)
        raise ClinicalAIValidationError(
            "AI_INVALID_OUTPUT",
            "The AI response was not valid structured data; please retry.",
        )
    return parsed, in_tokens, out_tokens


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Locate and parse the first JSON object in a model response."""
    if not raw:
        return None
    # Strip ```json fences if the model added them despite instructions.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{") :] if "{" in raw else raw
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _validate(result_cls: type, parsed: dict[str, Any], *, model: str, sources: list[str]):
    """Validate into the Pydantic schema; fail loudly on bad output.

    Server-controlled fields (``generated_by``, ``model``, ``disclaimer``,
    provenance ``sources``) are injected *before* validation so the model
    can never spoof or omit the AI-provenance envelope.
    """
    if not isinstance(parsed, dict):
        raise ClinicalAIValidationError("AI_INVALID_OUTPUT", "AI output was not an object.")
    payload = dict(parsed)
    payload["generated_by"] = "ai"
    payload["model"] = model
    if "sources" in result_cls.model_fields:
        payload["sources"] = list(
            dict.fromkeys([str(s) for s in (payload.get("sources") or []) if s] + list(sources))
        )
    try:
        return result_cls.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        raise ClinicalAIValidationError(
            "AI_INVALID_OUTPUT", f"AI output failed validation: {exc}"
        ) from exc


# --- deterministic signals (NOT AI) ------------------------------------


def _deterministic_signals(cc: ClinicalContext) -> list[DeterministicSignal]:
    """Rule-derived, authoritative clinical/operational signals."""
    signals: list[DeterministicSignal] = []

    open_recalls = [
        r for r in cc.recalls if str(r.get("status", "")).lower() not in ("done", "completed")
    ]
    if open_recalls:
        signals.append(
            DeterministicSignal(
                kind="open_recall",
                severity="attention",
                message=f"{len(open_recalls)} pending recall(s) for this patient.",
                source="recalls.list_due_recalls",
            )
        )

    pending_budgets = [
        b for b in cc.budgets if str(b.get("status", "")).lower() in ("sent", "pending", "expired")
    ]
    if pending_budgets:
        signals.append(
            DeterministicSignal(
                kind="pending_budget",
                severity="attention",
                message=f"{len(pending_budgets)} budget(s) awaiting patient response.",
                source="budget.list_budgets",
            )
        )

    if cc.patient.get("do_not_contact"):
        signals.append(
            DeterministicSignal(
                kind="do_not_contact",
                severity="warning",
                message="Patient is flagged do-not-contact.",
                source="patients.get_patient",
            )
        )

    # Payments returned a balance/debt? The tool surfaces a summary dict.
    debt = _digest_debt(cc.payments)
    if debt is not None:
        signals.append(
            DeterministicSignal(
                kind="outstanding_balance",
                severity="info" if debt == 0 else "attention",
                message=(
                    "No outstanding balance detected."
                    if debt == 0
                    else "Outstanding patient balance indicator present (see ledger)."
                ),
                source="payments.patient_payment_history",
            )
        )

    return signals


def _digest_debt(payments: dict[str, Any]) -> float | None:
    if not isinstance(payments, dict):
        return None
    for key in ("balance", "outstanding", "debt", "pending"):
        if key in payments:
            try:
                return float(payments[key])
            except (TypeError, ValueError):
                continue
    return None


# --- feature entry points ----------------------------------------------


async def _prepare(
    db: AsyncSession,
    *,
    clinic_id: UUID,
    user_id: UUID,
    role: str,
    permissions: list[str],
    patient_id: UUID,
) -> tuple[ClinicalContext, Any, str, Redactor]:
    from .clinical_context import PatientNotFoundError

    try:
        cc = await build_clinical_context(
            db,
            clinic_id=clinic_id,
            user_id=user_id,
            role=role,
            permissions=permissions,
            patient_id=patient_id,
        )
    except PatientNotFoundError as exc:
        raise ClinicalAIError("PATIENT_NOT_FOUND", "Patient not found in this clinic.") from exc

    provider, model, redaction_on = await _resolve_provider_and_model(db, clinic_id)
    redactor = Redactor(enabled=redaction_on)
    # Seed the redactor with the patient identity so name/phone/email are
    # tokenised in the prompt and restored on the way back.
    redactor.seed(
        {
            "patients": [
                {
                    "full_name": cc.patient.get("full_name"),
                    "phone": cc.patient.get("phone"),
                    "email": cc.patient.get("email"),
                }
            ]
        }
    )
    return cc, provider, model, redactor


def _context_block(cc: ClinicalContext) -> str:
    return (
        "PATIENT CASE DATA (structured, minimum-necessary; source-tagged). "
        "Use ONLY these facts. If a fact is absent, it is unknown — do not "
        "invent it.\n\n" + render_context_for_prompt(cc)
    )


async def generate_case_summary(db, **kw) -> CaseSummary:
    cc, provider, model, redactor = await _prepare(db, **kw)
    system = (
        "You are a senior dental-clinical assistant writing a concise CASE "
        "SUMMARY for the treating dentist, in English. Synthesise the "
        "structured patient data into a brief, factual summary. You are not a "
        "doctor and must not diagnose; note uncertainty and explicitly list "
        "any information that is missing."
    )
    user = (
        _context_block(cc) + "\n\nProduce the JSON case summary. `summary` = 2-4 sentences; "
        "populate the lists with short factual bullets grounded in the data."
    )
    parsed, _, _ = await _complete_json(
        provider=provider,
        model=model,
        system=system,
        user=user,
        result_cls=CaseSummary,
        redactor=redactor,
    )
    if not cc.timeline and not cc.budgets:
        parsed.setdefault("missing_information", [])
        parsed["missing_information"] = list(
            dict.fromkeys(
                [*parsed.get("missing_information", []), "No clinical/activity records available."]
            )
        )
        parsed["insufficient_information"] = True
    result = _validate(CaseSummary, parsed, model=model, sources=cc.sources)
    return result


async def generate_clinical_report(db, **kw) -> ClinicalReport:
    cc, provider, model, redactor = await _prepare(db, **kw)
    system = (
        "You are a dental-clinical reporting assistant. Produce a structured "
        "CLINICAL REPORT for dentist review from the supplied structured data. "
        "Organise findings into sections; every statement must trace to the "
        "provided data. Do not fabricate diagnoses, measurements or imaging. "
        "Clearly state missing information and uncertainty."
    )
    user = (
        _context_block(cc) + "\n\nProduce the JSON clinical report with an `overview`, "
        "`sections` (each {heading, body, findings[]}), `conclusions`, "
        "`recommendations` (advisory only), `missing_information`, "
        "`uncertainty`."
    )
    parsed, _, _ = await _complete_json(
        provider=provider,
        model=model,
        system=system,
        user=user,
        result_cls=ClinicalReport,
        redactor=redactor,
    )
    result = _validate(ClinicalReport, parsed, model=model, sources=cc.sources)
    return result


async def generate_second_review(db, **kw) -> SecondReview:
    cc, provider, model, redactor = await _prepare(db, **kw)
    system = (
        "You are providing an INDEPENDENT AI-ASSISTED SECOND REVIEW of a "
        "dental case for the treating dentist. Critically appraise the "
        "supplied data: surface key findings, possible concerns, "
        "inconsistencies, missing information, and questions the clinician "
        "should consider. You must NOT issue a definitive diagnosis or "
        "present yourself as medical authority; express confidence honestly "
        "(low/medium/high) with a short rationale, and default to low "
        "confidence when data is sparse."
    )
    user = (
        _context_block(cc) + "\n\nProduce the JSON second review. Be explicit that this is "
        "AI-assisted and non-authoritative in `overall_impression`."
    )
    parsed, _, _ = await _complete_json(
        provider=provider,
        model=model,
        system=system,
        user=user,
        result_cls=SecondReview,
        redactor=redactor,
    )
    # Safety: sparse data cannot be high confidence.
    if (
        len(cc.timeline) + len(cc.budgets) + len(cc.recalls) < 2
        and parsed.get("confidence") == "high"
    ):
        parsed["confidence"] = "low"
        parsed["confidence_rationale"] = (
            (parsed.get("confidence_rationale") or "")
            + " Downgraded: very little structured case data available."
        ).strip()
    result = _validate(SecondReview, parsed, model=model, sources=cc.sources)
    return result


async def generate_treatment_suggestions(db, **kw) -> TreatmentPlanAI:
    cc, provider, model, redactor = await _prepare(db, **kw)
    system = (
        "You are a dental treatment-planning assistant. Based ONLY on the "
        "supplied structured case data, propose advisory treatment OPTIONS "
        "for the dentist to consider. Order them logically (priority), give a "
        "rationale grounded in the data, list estimated steps, call out "
        "missing information, and express uncertainty. You do NOT execute, "
        "book, or create any treatment — the clinician decides. Do not invent "
        "clinical findings that are not present."
    )
    user = (
        _context_block(cc) + "\n\nProduce JSON: `options` (each {title, rationale, priority, "
        "estimated_steps[], depends_on_missing_info[], considerations[]}), "
        "`suggested_order` (option titles), `missing_information`, "
        "`uncertainty`."
    )
    parsed, _, _ = await _complete_json(
        provider=provider,
        model=model,
        system=system,
        user=user,
        result_cls=TreatmentPlanAI,
        redactor=redactor,
    )
    result = _validate(TreatmentPlanAI, parsed, model=model, sources=cc.sources)
    return result


async def generate_case_intelligence(db, **kw) -> CaseIntelligence:
    cc, provider, model, redactor = await _prepare(db, **kw)
    signals = _deterministic_signals(cc)
    system = (
        "You are a dental case-intelligence assistant. You receive a set of "
        "DETERMINISTIC, rule-derived signals plus structured case data. "
        "Provide clearly-labelled AI INSIGHTS (advisory, non-authoritative): "
        "important case signals, potential risks, missing follow-up, and "
        "attention points. Never present a deterministic signal as your own "
        "invention, and never fabricate facts. Distinguish what is observed "
        "(data) from what is suggested (your reasoning)."
    )
    user = (
        _context_block(cc)
        + "\n\nDETERMINISTIC SIGNALS (rules, authoritative):\n"
        + json.dumps([s.model_dump() for s in signals], ensure_ascii=False, default=str)
        + "\n\nProduce JSON: `insights` (AI-derived bullets), "
        "`risk_attention_points`, `missing_follow_up`, `missing_information`, "
        "`uncertainty`. Leave `signals` empty — the server attaches the "
        "deterministic signals."
    )
    parsed, _, _ = await _complete_json(
        provider=provider,
        model=model,
        system=system,
        user=user,
        result_cls=CaseIntelligence,
        redactor=redactor,
    )
    # Deterministic signals are authoritative and attached server-side;
    # never trust the model to populate them.
    parsed["signals"] = [s.model_dump() for s in signals]
    result = _validate(CaseIntelligence, parsed, model=model, sources=cc.sources)
    return result
