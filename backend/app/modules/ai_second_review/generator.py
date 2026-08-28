"""LLM adapter with strict traceability validation for AI Second Review."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, Usage
from app.modules.case_intelligence.contracts import canonical_json

from .contracts import (
    FindingCategory,
    SecondReviewContent,
    SecondReviewDataGap,
    SecondReviewFinding,
)

SYSTEM_PROMPT = """You perform an ADVISORY second review of one already dentist-accepted Dentora AI treatment-planning option and its deterministic Treatment Simulation.
Return JSON only with exactly: {"findings": [...], "data_gaps": [...]}.
Each finding must contain finding_id, category, statement, evidence_ids, risk_factor_ids, planning_refs, simulation_refs. Categories are evidence_traceability, risk_context, planning_consistency, simulation_consistency, safety_boundary. Report only discrepancies or review points that are directly grounded in the supplied structured artifacts. Reference only evidence ids, risk factor ids, planning refs, and simulation refs present in the input. Do not diagnose, recommend or select treatment, approve/reject a plan, infer missing facts, invent anatomy/findings/thresholds/probabilities, predict biological outcomes, or alter patient-space geometry. An empty findings list means only that no grounded discrepancy was identified in this limited review; it never means the treatment is safe, correct, optimal, or approved. Every case section marked not_available or invalid_or_stale must be represented exactly in data_gaps. This output is decision support only and requires dentist review."""


class _GeneratedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    category: FindingCategory
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    risk_factor_ids: list[str] = Field(default_factory=list)
    planning_refs: list[str] = Field(default_factory=list)
    simulation_refs: list[str] = Field(default_factory=list)


class _GeneratedGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    status: str
    reason: str | None = None


class _GeneratedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[_GeneratedFinding] = Field(default_factory=list)
    data_gaps: list[_GeneratedGap] = Field(default_factory=list)


@dataclass(frozen=True)
class GenerationResult:
    content: SecondReviewContent
    input_tokens: int | None = None
    output_tokens: int | None = None


class SecondReviewGenerationError(RuntimeError):
    pass


def _validate_refs(values: list[str], allowed: set[str], error: str) -> None:
    if any(value not in allowed for value in values):
        raise SecondReviewGenerationError(error)


async def generate_second_review(
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
        raise SecondReviewGenerationError(
            "provider_returned_invalid_structured_second_review"
        ) from exc

    case = llm_input["case"]
    allowed_evidence = set(case["evidence"])
    allowed_risk = {factor["factor_id"] for factor in llm_input["risk_context"]["factors"]}
    allowed_planning = set(llm_input["planning"]["allowed_refs"])
    allowed_simulation = set(llm_input["simulation"]["allowed_refs"])

    findings: list[SecondReviewFinding] = []
    seen_finding_ids: set[str] = set()
    for finding in generated.findings:
        if finding.finding_id in seen_finding_ids:
            raise SecondReviewGenerationError("duplicate_second_review_finding_id")
        seen_finding_ids.add(finding.finding_id)
        _validate_refs(
            finding.evidence_ids,
            allowed_evidence,
            "second_review_references_unknown_evidence",
        )
        _validate_refs(
            finding.risk_factor_ids,
            allowed_risk,
            "second_review_references_unknown_risk_factor",
        )
        _validate_refs(
            finding.planning_refs,
            allowed_planning,
            "second_review_references_unknown_planning_item",
        )
        _validate_refs(
            finding.simulation_refs,
            allowed_simulation,
            "second_review_references_unknown_simulation_item",
        )
        try:
            findings.append(SecondReviewFinding(**finding.model_dump()))
        except ValidationError as exc:
            raise SecondReviewGenerationError(
                "second_review_finding_requires_traceable_reference"
            ) from exc

    sections = case["sections"]
    gaps: list[SecondReviewDataGap] = []
    seen_gap_sections: set[str] = set()
    for gap in generated.data_gaps:
        section = sections.get(gap.section)
        if section is None:
            raise SecondReviewGenerationError("gap_references_unknown_section")
        expected_status = section["status"]
        if expected_status not in {"not_available", "invalid_or_stale"}:
            raise SecondReviewGenerationError("gap_status_does_not_match_snapshot")
        if gap.status != expected_status:
            raise SecondReviewGenerationError("gap_status_does_not_match_snapshot")
        if gap.section in seen_gap_sections:
            raise SecondReviewGenerationError("duplicate_data_gap")
        seen_gap_sections.add(gap.section)
        gaps.append(
            SecondReviewDataGap(
                section=gap.section,
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
        raise SecondReviewGenerationError("provider_omitted_or_invented_data_gap")

    return GenerationResult(
        content=SecondReviewContent(findings=findings, data_gaps=gaps),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
