"""LLM adapter with strict structured-output validation for treatment planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, Usage
from app.modules.case_intelligence.contracts import canonical_json

from .contracts import PlanningContent, PlanningDataGap, PlanningStep, TreatmentOption

SYSTEM_PROMPT = """You produce ADVISORY dental treatment-planning OPTIONS from one structured Dentora case projection and deterministic observed-fact risk context.
Return JSON only with exactly: {"options": [...], "data_gaps": [...]}.
Every option must contain option_id, title, clinical_intent, rationale, evidence_ids, risk_factor_ids, steps, uncertainties, alternatives_or_tradeoffs. Every step must contain step_id, description, purpose, evidence_ids, risk_factor_ids.
Use only case facts present in the input. Every option and every step must cite only evidence_ids provided in case.evidence, and every risk_factor_id must exist in risk_context.factors. Do not invent diagnoses, missing anatomy, test results, risk scores, validated thresholds, success probabilities, costs, medication doses, or autonomous implant dimensions. Do not claim a recommendation is mandatory, optimal, or final. Do not create or imply a canonical treatment plan. Do not simulate predicted outcomes. Represent every not_available or invalid_or_stale case section in data_gaps. If the available evidence is insufficient for a defensible option, return an empty options list and the required data gaps. The output is decision support only and requires dentist review."""


class _GeneratedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    description: str
    purpose: str
    evidence_ids: list[str] = Field(min_length=1)
    risk_factor_ids: list[str] = Field(default_factory=list)


class _GeneratedOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    title: str
    clinical_intent: str
    rationale: str
    evidence_ids: list[str] = Field(min_length=1)
    risk_factor_ids: list[str] = Field(default_factory=list)
    steps: list[_GeneratedStep] = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list)
    alternatives_or_tradeoffs: list[str] = Field(default_factory=list)


class _GeneratedGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    status: str
    reason: str | None = None


class _GeneratedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    options: list[_GeneratedOption] = Field(default_factory=list)
    data_gaps: list[_GeneratedGap] = Field(default_factory=list)


@dataclass(frozen=True)
class GenerationResult:
    content: PlanningContent
    input_tokens: int | None = None
    output_tokens: int | None = None


class PlanningGenerationError(RuntimeError):
    pass


def _validate_evidence(ids: list[str], allowed: set[str]) -> None:
    if any(evidence_id not in allowed for evidence_id in ids):
        raise PlanningGenerationError("planning_references_unknown_evidence")


def _validate_risk_factors(ids: list[str], allowed: set[str]) -> None:
    if any(factor_id not in allowed for factor_id in ids):
        raise PlanningGenerationError("planning_references_unknown_risk_factor")


async def generate_planning_options(
    *, provider: Provider, model: str, llm_input: dict[str, Any], max_tokens: int
) -> GenerationResult:
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
        response_schema=_GeneratedOutput.model_json_schema(),
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
        raise PlanningGenerationError("provider_returned_invalid_structured_planning") from exc

    case = llm_input["case"]
    allowed_evidence = set(case["evidence"])
    allowed_risk_factors = {factor["factor_id"] for factor in llm_input["risk_context"]["factors"]}

    options: list[TreatmentOption] = []
    seen_option_ids: set[str] = set()
    for generated_option in generated.options:
        if generated_option.option_id in seen_option_ids:
            raise PlanningGenerationError("duplicate_option_id")
        seen_option_ids.add(generated_option.option_id)
        _validate_evidence(generated_option.evidence_ids, allowed_evidence)
        _validate_risk_factors(generated_option.risk_factor_ids, allowed_risk_factors)

        steps: list[PlanningStep] = []
        seen_step_ids: set[str] = set()
        for generated_step in generated_option.steps:
            if generated_step.step_id in seen_step_ids:
                raise PlanningGenerationError("duplicate_step_id")
            seen_step_ids.add(generated_step.step_id)
            _validate_evidence(generated_step.evidence_ids, allowed_evidence)
            _validate_risk_factors(generated_step.risk_factor_ids, allowed_risk_factors)
            steps.append(PlanningStep(**generated_step.model_dump()))

        options.append(
            TreatmentOption(
                **generated_option.model_dump(exclude={"steps"}),
                steps=steps,
            )
        )

    gaps: list[PlanningDataGap] = []
    seen_gap_sections: set[str] = set()
    sections = case["sections"]
    for generated_gap in generated.data_gaps:
        section = sections.get(generated_gap.section)
        if section is None:
            raise PlanningGenerationError("gap_references_unknown_section")
        expected_status = section["status"]
        if expected_status not in {"not_available", "invalid_or_stale"}:
            raise PlanningGenerationError("gap_status_does_not_match_snapshot")
        if generated_gap.status != expected_status:
            raise PlanningGenerationError("gap_status_does_not_match_snapshot")
        if generated_gap.section in seen_gap_sections:
            raise PlanningGenerationError("duplicate_data_gap")
        seen_gap_sections.add(generated_gap.section)
        gaps.append(
            PlanningDataGap(
                section=generated_gap.section,
                status=expected_status,
                reason=section.get("reason"),
            )
        )

    required_gaps = {
        name
        for name, section in sections.items()
        if section["status"] in {"not_available", "invalid_or_stale"}
    }
    if seen_gap_sections != required_gaps:
        raise PlanningGenerationError("provider_omitted_or_invented_data_gap")

    return GenerationResult(
        content=PlanningContent(options=options, data_gaps=gaps),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
