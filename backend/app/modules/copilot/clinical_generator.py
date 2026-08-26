"""Strict structured-output LLM adapter for Clinical Copilot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, Usage

from .clinical_contracts import (
    ClinicalCopilotClaim,
    ClinicalCopilotContent,
    ClinicalCopilotLimitation,
)

SYSTEM_PROMPT = """You are Dentora Clinical Copilot, an ADVISORY decision-support surface for a licensed dentist.
You receive only a structured, redacted case projection plus deterministic risk context, a dentist-accepted treatment-planning artifact, its non-predictive Treatment Simulation, and a passed second-review consistency gate.
Return JSON only with exactly: {"summary": string, "claims": [...], "limitations": [...], "questions_for_dentist": [...]}.
Each claim must contain claim_id, text, evidence_ids, risk_factor_ids, planning_option_ids, simulation_checkpoint_ids and must cite at least one allowed reference from the input.
Use only facts present in the input. Never invent a diagnosis, finding, anatomy, test result, risk score, threshold, prognosis, success probability, medication dose, implant dimension, or treatment outcome. Never select, approve, execute, or mutate a treatment plan. Never claim a simulated checkpoint predicts a biological or geometric outcome. Do not call any tools.
Copy every required limitation exactly by section/status; do not omit not_available or invalid_or_stale data. If the evidence is insufficient for the requested focus, keep claims empty, explain the limitation in summary, and ask the dentist what evidence should be obtained or reviewed.
The dentist remains the sole clinical decision maker."""


class _GeneratedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    risk_factor_ids: list[str] = Field(default_factory=list)
    planning_option_ids: list[str] = Field(default_factory=list)
    simulation_checkpoint_ids: list[str] = Field(default_factory=list)


class _GeneratedLimitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    status: str
    reason: str | None = None


class _GeneratedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    claims: list[_GeneratedClaim] = Field(default_factory=list)
    limitations: list[_GeneratedLimitation] = Field(default_factory=list)
    questions_for_dentist: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class GenerationResult:
    content: ClinicalCopilotContent
    input_tokens: int | None = None
    output_tokens: int | None = None


class ClinicalCopilotGenerationError(RuntimeError):
    pass


def _assert_subset(values: list[str], allowed: set[str], error: str) -> None:
    if any(value not in allowed for value in values):
        raise ClinicalCopilotGenerationError(error)


async def generate_clinical_copilot(
    *, provider: Provider, model: str, llm_input: dict[str, Any], max_tokens: int
) -> GenerationResult:
    from app.modules.case_intelligence.contracts import canonical_json

    text_parts: list[str] = []
    input_tokens: int | None = None
    output_tokens: int | None = None
    messages = [ProviderMessage(Role.USER, [TextBlock(canonical_json(llm_input))])]
    async for event in provider.complete(
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=[],
        model=model,
        max_tokens=max_tokens,
    ):
        if isinstance(event, TextDelta):
            text_parts.append(event.text)
        elif isinstance(event, Usage):
            input_tokens = event.input_tokens
            output_tokens = event.output_tokens
        elif isinstance(event, Done):
            continue

    raw = "".join(text_parts).strip()
    try:
        generated = _GeneratedOutput.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ClinicalCopilotGenerationError(
            "provider_returned_invalid_structured_clinical_copilot_output"
        ) from exc

    allowed_evidence = set(llm_input["case"]["evidence"])
    allowed_risk = {factor["factor_id"] for factor in llm_input["risk_context"]["factors"]}
    allowed_options = {
        option["option_id"] for option in llm_input["reviewed_planning"]["options"]
    }
    allowed_checkpoints = {
        checkpoint["checkpoint_id"]
        for checkpoint in llm_input["reviewed_simulation"]["checkpoints"]
    }

    claims: list[ClinicalCopilotClaim] = []
    seen_claim_ids: set[str] = set()
    for item in generated.claims:
        if item.claim_id in seen_claim_ids:
            raise ClinicalCopilotGenerationError("duplicate_claim_id")
        seen_claim_ids.add(item.claim_id)
        if not (
            item.evidence_ids
            or item.risk_factor_ids
            or item.planning_option_ids
            or item.simulation_checkpoint_ids
        ):
            raise ClinicalCopilotGenerationError("clinical_copilot_claim_requires_traceability")
        _assert_subset(
            item.evidence_ids,
            allowed_evidence,
            "clinical_copilot_references_unknown_evidence",
        )
        _assert_subset(
            item.risk_factor_ids,
            allowed_risk,
            "clinical_copilot_references_unknown_risk_factor",
        )
        _assert_subset(
            item.planning_option_ids,
            allowed_options,
            "clinical_copilot_references_unknown_planning_option",
        )
        _assert_subset(
            item.simulation_checkpoint_ids,
            allowed_checkpoints,
            "clinical_copilot_references_unknown_simulation_checkpoint",
        )
        claims.append(ClinicalCopilotClaim(**item.model_dump()))

    expected_limitations = {
        (item["section"], item["status"]): item.get("reason")
        for item in llm_input["required_limitations"]
    }
    returned_keys: set[tuple[str, str]] = set()
    limitations: list[ClinicalCopilotLimitation] = []
    for item in generated.limitations:
        key = (item.section, item.status)
        if key not in expected_limitations:
            raise ClinicalCopilotGenerationError("clinical_copilot_invented_limitation")
        if key in returned_keys:
            raise ClinicalCopilotGenerationError("duplicate_clinical_copilot_limitation")
        returned_keys.add(key)
        limitations.append(
            ClinicalCopilotLimitation(
                section=item.section,
                status=item.status,
                reason=expected_limitations[key],
            )
        )
    if returned_keys != set(expected_limitations):
        raise ClinicalCopilotGenerationError("clinical_copilot_omitted_required_limitation")

    return GenerationResult(
        content=ClinicalCopilotContent(
            summary=generated.summary,
            claims=claims,
            limitations=limitations,
            questions_for_dentist=generated.questions_for_dentist,
        ),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


__all__ = [
    "ClinicalCopilotGenerationError",
    "GenerationResult",
    "generate_clinical_copilot",
]
