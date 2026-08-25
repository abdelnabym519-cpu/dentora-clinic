"""Strict LLM adapter for evidence-grounded advisory treatment planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, Usage
from app.modules.case_intelligence.contracts import canonical_json

from .treatment_contracts import (
    TreatmentDataGap,
    TreatmentPlanContent,
    TreatmentPlanOption,
    TreatmentPlanStep,
)

SYSTEM_PROMPT = """You produce advisory dental treatment-planning OPTIONS from one structured, redacted Dentora case projection.
Return JSON only with exactly: {"options": [...], "data_gaps": [...], "limitations": [...]}.
Each option must contain option_id, title, intent, and ordered steps. Each step must contain step_id, action, rationale, evidence_ids, prerequisites.
Every proposed action and rationale must be grounded only in evidence ids supplied in the input. Do not invent diagnoses, anatomy, measurements, medications, dosages, device sizes, surgical coordinates, clinical thresholds, or missing facts. Do not claim that a treatment is required, safe, optimal, completed, or approved. Treat unavailable or stale data as explicit data_gaps. The accepted AI case summary and accepted Risk Engine result are context, not authority. Provide alternatives when the evidence supports more than one reasonable path. Output is advisory only and requires independent dentist review; it must never mutate Dentora treatment-plan records."""


class _GeneratedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    action: str
    rationale: str
    evidence_ids: list[str] = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)


class _GeneratedOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str
    title: str
    intent: str
    steps: list[_GeneratedStep] = Field(min_length=1)


class _GeneratedGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: str
    status: str
    reason: str | None = None


class _GeneratedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    options: list[_GeneratedOption] = Field(default_factory=list)
    data_gaps: list[_GeneratedGap] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class TreatmentGenerationResult:
    content: TreatmentPlanContent
    input_tokens: int | None = None
    output_tokens: int | None = None


class TreatmentGenerationError(RuntimeError):
    pass


async def generate_treatment_plan(
    *, provider: Provider, model: str, llm_input: dict[str, Any], max_tokens: int
) -> TreatmentGenerationResult:
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
        raise TreatmentGenerationError("provider_returned_invalid_treatment_plan") from exc

    evidence_ids = set(llm_input["evidence"])
    sections = llm_input["sections"]
    options: list[TreatmentPlanOption] = []
    seen_options: set[str] = set()
    seen_steps: set[str] = set()
    for option in generated.options:
        if option.option_id in seen_options:
            raise TreatmentGenerationError("duplicate_option_id")
        seen_options.add(option.option_id)
        steps: list[TreatmentPlanStep] = []
        for step in option.steps:
            if step.step_id in seen_steps:
                raise TreatmentGenerationError("duplicate_step_id")
            seen_steps.add(step.step_id)
            if any(alias not in evidence_ids for alias in step.evidence_ids):
                raise TreatmentGenerationError("step_references_unknown_evidence")
            steps.append(TreatmentPlanStep(**step.model_dump()))
        options.append(
            TreatmentPlanOption(
                option_id=option.option_id,
                title=option.title,
                intent=option.intent,
                steps=steps,
            )
        )

    gaps: list[TreatmentDataGap] = []
    seen_gaps: set[str] = set()
    for gap in generated.data_gaps:
        section = sections.get(gap.section)
        if section is None:
            raise TreatmentGenerationError("gap_references_unknown_section")
        expected = section["status"]
        if expected not in {"not_available", "invalid_or_stale"} or gap.status != expected:
            raise TreatmentGenerationError("gap_status_does_not_match_snapshot")
        if gap.section in seen_gaps:
            raise TreatmentGenerationError("duplicate_data_gap")
        seen_gaps.add(gap.section)
        gaps.append(
            TreatmentDataGap(section=gap.section, status=gap.status, reason=section.get("reason"))
        )

    required_gaps = {
        name
        for name, section in sections.items()
        if section["status"] in {"not_available", "invalid_or_stale"}
    }
    if seen_gaps != required_gaps:
        raise TreatmentGenerationError("provider_omitted_or_invented_data_gap")

    return TreatmentGenerationResult(
        content=TreatmentPlanContent(
            options=options,
            data_gaps=gaps,
            limitations=generated.limitations,
        ),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
