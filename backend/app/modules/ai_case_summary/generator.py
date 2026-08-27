"""LLM adapter for strict evidence-traceable summary generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, Usage
from app.modules.case_intelligence.contracts import canonical_json

from .contracts import SummaryClaim, SummaryContent, SummaryDataGap

SYSTEM_PROMPT = """You produce an advisory dental case summary from ONE structured Dentora CaseSnapshot projection.
Return JSON only, with exactly: {"claims": [...], "data_gaps": [...]}.
Each claim must have claim_id, text, evidence_ids. Use only facts present in the input and only evidence ids that the input provides. Do not diagnose, issue a clinical verdict, recommend treatment, assign risk scores/bands, invent thresholds, infer missing anatomy, or fill unavailable/stale data. Data with status not_available or invalid_or_stale must be represented in data_gaps rather than converted into a clinical fact. Keep claims concise and factual and return no more than 8 claims. The output is advisory and requires dentist review."""


class _GeneratedGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: str
    status: str
    reason: str | None = None


class _GeneratedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class _GeneratedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[_GeneratedClaim] = Field(default_factory=list, max_length=8)
    data_gaps: list[_GeneratedGap] = Field(default_factory=list)


@dataclass(frozen=True)
class GenerationResult:
    content: SummaryContent
    input_tokens: int | None = None
    output_tokens: int | None = None


class SummaryGenerationError(RuntimeError):
    pass


async def generate_summary(
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
        parsed = json.loads(raw)
        generated = _GeneratedOutput.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise SummaryGenerationError("provider_returned_invalid_structured_summary") from exc

    evidence_ids = set(llm_input["evidence"])
    sections = llm_input["sections"]
    claims: list[SummaryClaim] = []
    seen_claim_ids: set[str] = set()
    for claim in generated.claims:
        if claim.claim_id in seen_claim_ids:
            raise SummaryGenerationError("duplicate_claim_id")
        seen_claim_ids.add(claim.claim_id)
        if any(alias not in evidence_ids for alias in claim.evidence_ids):
            raise SummaryGenerationError("claim_references_unknown_evidence")
        claims.append(SummaryClaim(**claim.model_dump()))

    gaps: list[SummaryDataGap] = []
    seen_gaps: set[str] = set()
    for gap in generated.data_gaps:
        section = sections.get(gap.section)
        if section is None:
            raise SummaryGenerationError("gap_references_unknown_section")
        if section["status"] not in {"not_available", "invalid_or_stale"}:
            raise SummaryGenerationError("gap_status_does_not_match_snapshot")
        if gap.status != section["status"]:
            raise SummaryGenerationError("gap_status_does_not_match_snapshot")
        if gap.section in seen_gaps:
            raise SummaryGenerationError("duplicate_data_gap")
        seen_gaps.add(gap.section)
        gaps.append(
            SummaryDataGap(section=gap.section, status=gap.status, reason=section.get("reason"))
        )

    required_gaps = {
        name
        for name, section in sections.items()
        if section["status"] in {"not_available", "invalid_or_stale"}
    }
    if seen_gaps != required_gaps:
        raise SummaryGenerationError("provider_omitted_or_invented_data_gap")

    return GenerationResult(
        content=SummaryContent(claims=claims, data_gaps=gaps),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
