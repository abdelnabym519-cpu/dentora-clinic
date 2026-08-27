"""Safety policy facade for Clinical Copilot execution.

This layer deliberately reuses the existing read-only ClinicalCopilotService and the
vendor-neutral LLM Provider protocol. It adds cross-stage readiness enforcement and a
provider-boundary projection without changing canonical clinical records.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from app.core.llm.base import (
    Done,
    Provider,
    ProviderEvent,
    ProviderMessage,
    TextBlock,
    TextDelta,
)

from .contracts import (
    ClinicalCopilotAdvisory,
    ClinicalCopilotContext,
    ClinicalCopilotFocus,
    StageName,
    StageState,
)
from .service import ClinicalCopilotService, _canonical, _digest


class ClinicalCopilotInputError(ValueError):
    """Raised before context/provider execution when the finite focus contract is violated."""


_PROVIDER_DROP_KEYS = {
    "artifact_id",
    "clinic_id",
    "generated_by",
    "patient_id",
    "planning_id",
    "reviewed_by",
    "simulation_id",
    "source_record_id",
}
_EVIDENCE_SCALAR_KEYS = {"evidence_id"}
_EVIDENCE_LIST_KEYS = {"allowed_evidence_ids", "evidence_ids", "evidence_refs"}


def _opaque_alias(value: Any, aliases: dict[str, str], prefix: str) -> str:
    raw = str(value)
    alias = aliases.get(raw)
    if alias is None:
        alias = f"{prefix}{len(aliases) + 1:03d}"
        aliases[raw] = alias
    return alias


def _project_provider_value(
    value: Any,
    *,
    evidence_aliases: dict[str, str],
    identifier_aliases: dict[str, str],
) -> Any:
    """Project structured evidence to opaque provider-safe identifiers."""
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _PROVIDER_DROP_KEYS or lowered.endswith("_digest"):
                continue
            if lowered in _EVIDENCE_SCALAR_KEYS and item is not None:
                projected[str(key)] = _opaque_alias(item, evidence_aliases, "E")
                continue
            if lowered in _EVIDENCE_LIST_KEYS and isinstance(item, list):
                projected[str(key)] = [
                    _opaque_alias(entry, evidence_aliases, "E") for entry in item if entry
                ]
                continue
            if lowered.endswith("_id") and item is not None:
                projected[str(key)] = _opaque_alias(item, identifier_aliases, "I")
                continue
            if lowered.endswith("_ids") and isinstance(item, list):
                projected[str(key)] = [
                    _opaque_alias(entry, identifier_aliases, "I") for entry in item if entry
                ]
                continue
            projected[str(key)] = _project_provider_value(
                item,
                evidence_aliases=evidence_aliases,
                identifier_aliases=identifier_aliases,
            )
        return projected
    if isinstance(value, list):
        return [
            _project_provider_value(
                item,
                evidence_aliases=evidence_aliases,
                identifier_aliases=identifier_aliases,
            )
            for item in value
        ]
    return value


def _provider_projection(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    raw_allowed = [str(item) for item in payload.get("allowed_evidence_ids", []) if item]
    evidence_aliases = {raw: f"E{index:03d}" for index, raw in enumerate(raw_allowed, start=1)}
    identifier_aliases: dict[str, str] = {}
    projected = _project_provider_value(
        payload,
        evidence_aliases=evidence_aliases,
        identifier_aliases=identifier_aliases,
    )
    reverse_evidence = {alias: raw for raw, alias in evidence_aliases.items()}
    return projected, reverse_evidence


def _rehydrate_provider_output(value: Any, reverse_evidence: dict[str, str]) -> Any:
    if isinstance(value, dict):
        hydrated: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _EVIDENCE_SCALAR_KEYS and item is not None:
                hydrated[str(key)] = reverse_evidence.get(str(item), str(item))
            elif lowered in _EVIDENCE_LIST_KEYS and isinstance(item, list):
                hydrated[str(key)] = [
                    reverse_evidence.get(str(entry), str(entry)) for entry in item
                ]
            else:
                hydrated[str(key)] = _rehydrate_provider_output(item, reverse_evidence)
        return hydrated
    if isinstance(value, list):
        return [_rehydrate_provider_output(item, reverse_evidence) for item in value]
    return value


class ProviderBoundaryProxy:
    """Opaque-ID adapter around Dentora's existing vendor-neutral Provider port."""

    def __init__(self, upstream: Provider) -> None:
        self.upstream = upstream
        self.provider_payload: dict[str, Any] | None = None

    def complete(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        tools: list[dict],
        model: str,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        if len(messages) != 1 or len(messages[0].content) != 1:
            raise ClinicalCopilotInputError("provider_boundary_message_shape_invalid")
        block = messages[0].content[0]
        if not isinstance(block, TextBlock):
            raise ClinicalCopilotInputError("provider_boundary_message_shape_invalid")
        try:
            raw_payload = json.loads(block.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ClinicalCopilotInputError("provider_boundary_payload_invalid") from exc
        if not isinstance(raw_payload, dict):
            raise ClinicalCopilotInputError("provider_boundary_payload_invalid")

        projected, reverse_evidence = _provider_projection(raw_payload)
        self.provider_payload = projected
        outbound = [
            ProviderMessage(
                role=messages[0].role,
                content=[TextBlock(text=_canonical(projected))],
            )
        ]

        async def stream() -> AsyncIterator[ProviderEvent]:
            chunks: list[str] = []
            terminal: Done | None = None
            async for event in self.upstream.complete(
                system=system,
                messages=outbound,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                response_schema=response_schema,
            ):
                if isinstance(event, TextDelta):
                    chunks.append(event.text)
                elif isinstance(event, Done):
                    terminal = event
                else:
                    yield event

            raw_text = "".join(chunks)
            try:
                parsed = json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                yield TextDelta(text=raw_text)
            else:
                yield TextDelta(
                    text=_canonical(_rehydrate_provider_output(parsed, reverse_evidence))
                )
            if terminal is not None:
                yield terminal

        return stream()


def _enforce_cross_stage_readiness(
    context: ClinicalCopilotContext,
) -> ClinicalCopilotContext:
    """Risk must be READY before Planning and every downstream stage can be READY."""
    by_stage = {stage.stage: stage for stage in context.stages}
    risk = by_stage.get(StageName.RISK_ENGINE)
    planning = by_stage.get(StageName.TREATMENT_PLANNING)
    simulation = by_stage.get(StageName.TREATMENT_SIMULATION)
    second_review = by_stage.get(StageName.AI_SECOND_REVIEW)

    if risk is not None and risk.state is not StageState.READY:
        if planning is not None and planning.state is StageState.READY:
            planning.state = StageState.STALE
            planning.reason = "treatment_planning_risk_not_ready"
        if simulation is not None and simulation.state is StageState.READY:
            simulation.state = StageState.STALE
            simulation.reason = "treatment_simulation_planning_not_ready"
        if second_review is not None and second_review.state is StageState.READY:
            second_review.state = StageState.STALE
            second_review.reason = "ai_second_review_simulation_not_ready"

    context.missing_or_stale = [
        f"{stage.stage}:{stage.state}:{stage.reason or 'not_ready'}"
        for stage in context.stages
        if stage.state is not StageState.READY
    ]
    context.ready_for_advice = not context.missing_or_stale
    context.input_digest = _digest(
        {
            "clinic_id": str(context.clinic_id),
            "patient_id": str(context.patient_id),
            "stages": [stage.model_dump(mode="json") for stage in context.stages],
            "catalog": context.evidence_catalog,
        }
    )
    return context


class ClinicalCopilotGuardedService(ClinicalCopilotService):
    """Clinical Copilot execution policy on top of the existing read-only service."""

    async def build_context(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        redactor=None,
    ) -> ClinicalCopilotContext:
        context = await super().build_context(
            clinic_id=clinic_id,
            patient_id=patient_id,
            redactor=redactor,
        )
        return _enforce_cross_stage_readiness(context)

    async def advise(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        focus: str | ClinicalCopilotFocus,
        provider: Provider,
        provider_name: str,
        model: str,
        user_id: UUID,
        user_role: str,
    ) -> ClinicalCopilotAdvisory:
        if user_role != "dentist":
            raise PermissionError("dentist_control_required")
        try:
            finite_focus = ClinicalCopilotFocus(str(focus))
        except ValueError as exc:
            raise ClinicalCopilotInputError("clinical_copilot_focus_invalid") from exc

        boundary = ProviderBoundaryProxy(provider)
        result = await super().advise(
            clinic_id=clinic_id,
            patient_id=patient_id,
            focus=finite_focus.value,
            provider=boundary,
            provider_name=provider_name,
            model=model,
            user_id=user_id,
            user_role=user_role,
        )
        if boundary.provider_payload is None:
            raise ClinicalCopilotInputError("provider_boundary_payload_missing")
        result.provenance.input_digest = _digest(boundary.provider_payload)
        return result
