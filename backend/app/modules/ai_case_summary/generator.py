"""LLM adapter for deterministic evidence-grounded summary generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, Usage
from app.modules.case_intelligence.contracts import canonical_json

from .contracts import SummaryClaim, SummaryContent, SummaryDataGap

SYSTEM_PROMPT = """You select advisory dental case facts from ONE structured Dentora CaseSnapshot projection.
Return JSON only, with exactly: {"claims": [...]}.

Each claim must contain:
- claim_id
- evidence_id
- fact_paths

evidence_id must reference exactly one evidence object supplied in the input.
fact_paths must be dot-separated paths to scalar values that actually exist inside that evidence object's "facts".
A claim must never combine facts from different evidence records.

Do NOT write free-text clinical claims. Dentora renders the selected facts deterministically.
Do NOT diagnose, issue a clinical verdict, recommend treatment, assign risk scores/bands,
invent thresholds, infer missing anatomy, or fill unavailable/stale data.
Do not select null, object, or list values as terminal facts.
Return no more than 8 claims and no more than 6 fact paths per claim.
Missing/stale data gaps are derived deterministically by Dentora and are never delegated to the provider.
The result is advisory and requires dentist review.
"""


class _GeneratedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    evidence_id: str
    fact_paths: list[str] = Field(min_length=1, max_length=6)


class _GeneratedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[_GeneratedClaim] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True)
class GenerationResult:
    content: SummaryContent
    input_tokens: int | None = None
    output_tokens: int | None = None


class SummaryGenerationError(RuntimeError):
    pass


def _resolve_fact(facts: dict[str, Any], path: str) -> Any:
    if not path or path.startswith(".") or path.endswith(".") or ".." in path:
        raise SummaryGenerationError("claim_references_unknown_fact_path")

    current: Any = facts
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise SummaryGenerationError("claim_references_unknown_fact_path")
            current = current[part]
            continue

        if isinstance(current, list):
            if not part.isdigit():
                raise SummaryGenerationError("claim_references_unknown_fact_path")
            index = int(part)
            if index >= len(current):
                raise SummaryGenerationError("claim_references_unknown_fact_path")
            current = current[index]
            continue

        raise SummaryGenerationError("claim_references_unknown_fact_path")

    if current is None or isinstance(current, (dict, list)):
        raise SummaryGenerationError("claim_fact_is_not_scalar")

    return current


def _fact_label(path: str) -> str:
    return path.split(".")[-1].replace("_", " ")


def _fact_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value.replace("_", " ")
    return str(value)


def _render_claim(section: str, selected: list[tuple[str, Any]]) -> str:
    section_label = section.replace("_", " ").title()
    facts = "; ".join(f"{_fact_label(path)}: {_fact_value(value)}" for path, value in selected)
    return f"{section_label} — {facts}."


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

    evidence = llm_input["evidence"]
    claims: list[SummaryClaim] = []
    seen_claim_ids: set[str] = set()

    for claim in generated.claims:
        if claim.claim_id in seen_claim_ids:
            raise SummaryGenerationError("duplicate_claim_id")
        seen_claim_ids.add(claim.claim_id)

        evidence_item = evidence.get(claim.evidence_id)
        if not isinstance(evidence_item, dict):
            raise SummaryGenerationError("claim_references_unknown_evidence")

        section = evidence_item.get("section")
        facts = evidence_item.get("facts")

        if not isinstance(section, str) or not isinstance(facts, dict):
            raise SummaryGenerationError("claim_references_ungrounded_evidence")

        selected: list[tuple[str, Any]] = []
        seen_paths: set[str] = set()

        for path in claim.fact_paths:
            if path in seen_paths:
                raise SummaryGenerationError("duplicate_claim_fact_path")
            seen_paths.add(path)

            value = _resolve_fact(facts, path)
            selected.append((path, value))

        claims.append(
            SummaryClaim(
                claim_id=claim.claim_id,
                text=_render_claim(section, selected),
                evidence_ids=[claim.evidence_id],
            )
        )

    sections = llm_input["sections"]

    gaps = [
        SummaryDataGap(
            section=name,
            status=section["status"],
            reason=section.get("reason"),
        )
        for name, section in sorted(sections.items())
        if section["status"] in {"not_available", "invalid_or_stale"}
    ]

    return GenerationResult(
        content=SummaryContent(claims=claims, data_gaps=gaps),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
