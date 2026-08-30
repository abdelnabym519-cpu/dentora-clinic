"""LLM adapter with deterministic semantic grounding for treatment planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, Usage
from app.modules.case_intelligence.contracts import canonical_json

from .contracts import PlanningContent, PlanningDataGap, PlanningStep, TreatmentOption

StrategyCode = Literal[
    "review_documented_findings",
    "monitor_documented_state",
    "stage_clinical_decision",
    "compare_existing_options",
]

SYSTEM_PROMPT = """You select safe ADVISORY dental treatment-planning strategies from one structured Dentora case projection and deterministic observed-fact risk context.
Return JSON only with exactly: {"options": [...]}.
Each option must contain option_id, strategy, evidence, risk_factor_ids, and steps.
Each step must contain step_id, strategy, evidence, and risk_factor_ids.
Each evidence item must contain exactly one evidence_id plus fact_paths that resolve to scalar values inside that evidence record's facts.
Allowed strategy values are: review_documented_findings, monitor_documented_state, stage_clinical_decision, compare_existing_options.
Use only evidence records and scalar fact paths present in case.evidence. Use only risk_factor_ids present in risk_context.factors.
Do not write clinical prose, diagnoses, treatment procedures, anatomy, test results, success probabilities, costs, medication doses, implant dimensions, or data gaps. Dentora renders all public text and derives data gaps deterministically.
If available evidence is insufficient for a defensible advisory option, return an empty options list.
The result is decision support only, requires dentist review, and never creates or executes a canonical treatment plan."""


class _GeneratedEvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    fact_paths: list[str] = Field(min_length=1, max_length=4)


class _GeneratedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    strategy: StrategyCode
    evidence: list[_GeneratedEvidenceSelection] = Field(min_length=1, max_length=4)
    risk_factor_ids: list[str] = Field(default_factory=list, max_length=8)


class _GeneratedOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    strategy: StrategyCode
    evidence: list[_GeneratedEvidenceSelection] = Field(min_length=1, max_length=4)
    risk_factor_ids: list[str] = Field(default_factory=list, max_length=8)
    steps: list[_GeneratedStep] = Field(min_length=1, max_length=4)


class _GeneratedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    options: list[_GeneratedOption] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True)
class GenerationResult:
    content: PlanningContent
    input_tokens: int | None = None
    output_tokens: int | None = None


class PlanningGenerationError(RuntimeError):
    pass


_STRATEGY_TEXT = {
    "review_documented_findings": {
        "title": "Review documented {sections} findings",
        "intent": "Review the documented findings before choosing or changing treatment.",
        "step": "Review the documented {sections} evidence.",
        "purpose": "Keep the clinical decision tied to the current structured record.",
        "tradeoff": "No treatment action is selected automatically.",
    },
    "monitor_documented_state": {
        "title": "Monitor documented {sections} state",
        "intent": "Monitor the documented state and reassess before changing treatment.",
        "step": "Monitor the documented {sections} findings and reassess as clinically appropriate.",
        "purpose": "Avoid changing treatment without a documented basis.",
        "tradeoff": "Monitoring may defer a treatment decision until the dentist reassesses the case.",
    },
    "stage_clinical_decision": {
        "title": "Stage the clinical decision for {sections}",
        "intent": "Use a staged dentist-led decision process based on the documented evidence.",
        "step": "Stage the decision using the documented {sections} evidence.",
        "purpose": "Keep each decision step traceable to current structured evidence.",
        "tradeoff": "The final treatment choice remains pending until dentist review.",
    },
    "compare_existing_options": {
        "title": "Compare documented options for {sections}",
        "intent": "Compare only options already represented by the documented structured evidence.",
        "step": "Compare the documented {sections} evidence without creating a new treatment order.",
        "purpose": "Support dentist comparison while preserving the canonical treatment-plan boundary.",
        "tradeoff": "Dentora does not select or execute a canonical treatment option automatically.",
    },
}


def _validate_risk_factors(ids: list[str], allowed: set[str]) -> None:
    if any(factor_id not in allowed for factor_id in ids):
        raise PlanningGenerationError("planning_references_unknown_risk_factor")
    if len(ids) != len(set(ids)):
        raise PlanningGenerationError("duplicate_risk_factor_id")


def _resolve_fact(facts: Any, path: str) -> Any:
    if not path or path.startswith(".") or path.endswith(".") or ".." in path:
        raise PlanningGenerationError("planning_references_unknown_fact_path")

    current = facts
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise PlanningGenerationError("planning_references_unknown_fact_path")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise PlanningGenerationError("planning_references_unknown_fact_path") from exc
            if index < 0 or index >= len(current):
                raise PlanningGenerationError("planning_references_unknown_fact_path")
            current = current[index]
        else:
            raise PlanningGenerationError("planning_references_unknown_fact_path")

    if current is None or isinstance(current, (dict, list)):
        raise PlanningGenerationError("planning_fact_is_not_scalar")
    return current


def _validate_evidence_selections(
    selections: list[_GeneratedEvidenceSelection],
    evidence: dict[str, dict[str, Any]],
) -> tuple[list[str], list[tuple[str, str, str, Any]]]:
    evidence_ids: list[str] = []
    selected_facts: list[tuple[str, str, str, Any]] = []
    seen_evidence: set[str] = set()

    for selection in selections:
        if selection.evidence_id in seen_evidence:
            raise PlanningGenerationError("duplicate_evidence_id")
        seen_evidence.add(selection.evidence_id)

        record = evidence.get(selection.evidence_id)
        if record is None:
            raise PlanningGenerationError("planning_references_unknown_evidence")

        facts = record.get("facts", {})
        section = record.get("section") or "case"
        seen_paths: set[str] = set()

        for path in selection.fact_paths:
            if path in seen_paths:
                raise PlanningGenerationError("duplicate_fact_path")
            seen_paths.add(path)
            value = _resolve_fact(facts, path)
            selected_facts.append((selection.evidence_id, section, path, value))

        evidence_ids.append(selection.evidence_id)

    return evidence_ids, selected_facts


def _fact_label(path: str) -> str:
    return path.split(".")[-1].replace("_", " ")


def _fact_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return text if len(text) <= 120 else f"{text[:117]}..."


def _section_label(selected: list[tuple[str, str, str, Any]]) -> str:
    sections = []
    for _, section, _, _ in selected:
        label = section.replace("_", " ").title()
        if label not in sections:
            sections.append(label)
    if not sections:
        return "case"
    if len(sections) <= 2:
        return " and ".join(sections)
    return f"{sections[0]}, {sections[1]}, and related"


def _render_basis(
    selected: list[tuple[str, str, str, Any]],
    *,
    max_length: int = 1200,
) -> str:
    parts = [
        f"{section.replace('_', ' ').title()} {_fact_label(path)}: {_fact_value(value)}"
        for _, section, path, value in selected
    ]
    text = "; ".join(parts)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _render_risk_context(
    ids: list[str],
    risk_lookup: dict[str, dict[str, Any]],
) -> str:
    if not ids:
        return ""
    parts = []
    for factor_id in ids:
        factor = risk_lookup[factor_id]
        label = factor.get("label") or factor_id.replace("_", " ")
        state = factor.get("state") or "unknown"
        parts.append(f"{label}: {state}")
    text = "; ".join(parts)
    return text if len(text) <= 300 else f"{text[:297]}..."


def _render_option(
    generated: _GeneratedOption,
    *,
    evidence: dict[str, dict[str, Any]],
    risk_lookup: dict[str, dict[str, Any]],
) -> TreatmentOption:
    evidence_ids, selected = _validate_evidence_selections(generated.evidence, evidence)
    allowed_risk_factors = set(risk_lookup)
    _validate_risk_factors(generated.risk_factor_ids, allowed_risk_factors)

    strategy = _STRATEGY_TEXT[generated.strategy]
    sections = _section_label(selected)
    rationale = f"Documented basis: {_render_basis(selected)}."
    rendered_risk = _render_risk_context(generated.risk_factor_ids, risk_lookup)
    if rendered_risk:
        rationale += f" Deterministic risk context: {rendered_risk}."

    steps: list[PlanningStep] = []
    seen_step_ids: set[str] = set()
    for generated_step in generated.steps:
        if generated_step.step_id in seen_step_ids:
            raise PlanningGenerationError("duplicate_step_id")
        seen_step_ids.add(generated_step.step_id)

        step_evidence_ids, step_selected = _validate_evidence_selections(
            generated_step.evidence,
            evidence,
        )
        _validate_risk_factors(generated_step.risk_factor_ids, allowed_risk_factors)
        step_strategy = _STRATEGY_TEXT[generated_step.strategy]
        step_sections = _section_label(step_selected)
        step_basis = _render_basis(step_selected, max_length=800)
        description = (
            f"{step_strategy['step'].format(sections=step_sections)} "
            f"Documented basis: {step_basis}."
        )

        steps.append(
            PlanningStep(
                step_id=generated_step.step_id,
                description=description,
                purpose=step_strategy["purpose"],
                evidence_ids=step_evidence_ids,
                risk_factor_ids=generated_step.risk_factor_ids,
            )
        )

    return TreatmentOption(
        option_id=generated.option_id,
        title=strategy["title"].format(sections=sections),
        clinical_intent=strategy["intent"],
        rationale=rationale,
        evidence_ids=evidence_ids,
        risk_factor_ids=generated.risk_factor_ids,
        steps=steps,
        uncertainties=[],
        alternatives_or_tradeoffs=[strategy["tradeoff"]],
    )


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
    evidence = case["evidence"]
    risk_lookup = {
        factor["factor_id"]: factor for factor in llm_input["risk_context"]["factors"]
    }

    options: list[TreatmentOption] = []
    seen_option_ids: set[str] = set()
    for generated_option in generated.options:
        if generated_option.option_id in seen_option_ids:
            raise PlanningGenerationError("duplicate_option_id")
        seen_option_ids.add(generated_option.option_id)
        options.append(
            _render_option(
                generated_option,
                evidence=evidence,
                risk_lookup=risk_lookup,
            )
        )

    sections = case["sections"]
    gaps = [
        PlanningDataGap(
            section=name,
            status=section["status"],
            reason=section.get("reason"),
        )
        for name, section in sorted(sections.items())
        if section["status"] in {"not_available", "invalid_or_stale"}
    ]

    return GenerationResult(
        content=PlanningContent(options=options, data_gaps=gaps),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
