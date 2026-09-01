"""Deterministic privacy and grounding boundary for AI Treatment Planning input."""

from __future__ import annotations

from typing import Any

from app.core.agents.redaction import Redactor
from app.modules.case_intelligence.contracts import CaseSection, CaseSnapshot, digest_value
from app.modules.risk_engine.contracts import RiskFactor
from app.modules.risk_engine.engine import RiskEvaluation

from .contracts import AI_TREATMENT_PLANNING_INPUT_VERSION

_BLOCKED_EXACT = {
    "id",
    "clinic_id",
    "patient_id",
    "date_of_birth",
    "first_name",
    "last_name",
    "full_name",
    "name",
    "email",
    "phone",
    "mobile",
    "telephone",
    "national_id",
    "dni",
    "nif",
    "tax_id",
    "notes",
    "note",
    "title",
    "description",
    "reaction",
    "complications",
    "procedure",
    "anesthesia_reaction_details",
    "displacement_notes",
    "event_data",
    "extra_data",
    "tags",
}
_BLOCKED_FRAGMENTS = ("note", "comment", "description", "free_text", "narrative")


def _blocked_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in _BLOCKED_EXACT
        or lowered.endswith("_id")
        or any(fragment in lowered for fragment in _BLOCKED_FRAGMENTS)
    )


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items() if not _blocked_key(key)}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _evidence_key(ref) -> tuple[str, str, str, str, str, str]:
    return (
        ref.source_module,
        ref.source_entity,
        ref.source_record_id or "",
        ref.source_version or "",
        ref.source_digest or "",
        ref.validation_state or "",
    )


def _evidence_aliases(snapshot: CaseSnapshot) -> tuple[list, dict[tuple, str]]:
    unique = {_evidence_key(ref): ref for ref in snapshot.provenance}
    ordered = [unique[key] for key in sorted(unique)]
    aliases = {_evidence_key(ref): f"E{index:03d}" for index, ref in enumerate(ordered, 1)}
    return ordered, aliases


def _section_payload(section: CaseSection, aliases: dict[tuple, str]) -> dict[str, Any]:
    return {
        "status": section.status.value,
        "data": _sanitize(section.data),
        "evidence_ids": [
            aliases[_evidence_key(ref)] for ref in section.evidence if _evidence_key(ref) in aliases
        ],
        "reason": section.reason,
    }


def _find_record_by_id(value: Any, record_id: str | None) -> dict[str, Any] | None:
    if record_id is None:
        return None

    if isinstance(value, dict):
        candidate_id = value.get("id")
        if candidate_id is not None and str(candidate_id) == str(record_id):
            return value
        for item in value.values():
            found = _find_record_by_id(item, record_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_record_by_id(item, record_id)
            if found is not None:
                return found
    return None


def _evidence_facts(
    *,
    section_name: str,
    section: CaseSection,
    aliases: dict[tuple, str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    single_evidence = len(section.evidence) == 1

    for ref in section.evidence:
        alias = aliases[_evidence_key(ref)]
        matched = _find_record_by_id(section.data, ref.source_record_id)

        if matched is not None:
            facts = _sanitize(matched)
        elif single_evidence and isinstance(section.data, dict):
            facts = _sanitize(section.data)
        else:
            facts = {}

        result[alias] = {
            "section": section_name,
            "facts": facts,
        }

    return result


def _risk_factor_payload(factor: RiskFactor) -> dict[str, Any]:
    return {
        "factor_id": factor.factor_id,
        "label": factor.label,
        "state": factor.state.value,
        "display_band": factor.display_band.value,
        "evidence_ids": list(factor.evidence_ids),
        "observed_value": factor.observed_value,
        "unit": factor.unit,
        "semantics": factor.semantics,
    }


def build_planning_llm_input(
    snapshot: CaseSnapshot, risk_evaluation: RiskEvaluation
) -> tuple[dict[str, Any], str]:
    """Return the canonical redacted audit input plus deterministic digest."""
    ordered_refs, aliases = _evidence_aliases(snapshot)

    evidence = {
        aliases[_evidence_key(ref)]: {
            "source_module": ref.source_module,
            "source_entity": ref.source_entity,
            "source_version": ref.source_version,
            "validation_state": ref.validation_state,
        }
        for ref in ordered_refs
    }

    evidence_facts: dict[str, dict[str, Any]] = {}
    evidence_facts.update(
        _evidence_facts(
            section_name="reference_frame",
            section=snapshot.reference_frame,
            aliases=aliases,
        )
    )
    for name, section in sorted(snapshot.clinical_state.items()):
        evidence_facts.update(
            _evidence_facts(
                section_name=name,
                section=section,
                aliases=aliases,
            )
        )

    for alias, grounded in evidence_facts.items():
        if alias in evidence:
            evidence[alias]["section"] = grounded["section"]
            evidence[alias]["facts"] = grounded["facts"]

    case_payload = {
        "case_snapshot_contract_version": snapshot.contract_version,
        "case_snapshot_version": snapshot.case_snapshot_version,
        "case_source_digest": snapshot.source_digest,
        "reference_frame": _section_payload(snapshot.reference_frame, aliases),
        "sections": {
            name: _section_payload(section, aliases)
            for name, section in sorted(snapshot.clinical_state.items())
        },
        "availability": {
            name: status.value for name, status in sorted(snapshot.availability.items())
        },
        "missing_data_report": sorted(snapshot.missing_data_report),
        "evidence": evidence,
    }
    payload = {
        "input_contract_version": AI_TREATMENT_PLANNING_INPUT_VERSION,
        "case": case_payload,
        "risk_context": {
            "availability_state": risk_evaluation.availability_state,
            "input_digest": risk_evaluation.input_digest,
            "result_digest": risk_evaluation.result_digest,
            "factors": [_risk_factor_payload(factor) for factor in risk_evaluation.factors],
        },
        "guardrails": {
            "advisory_only": True,
            "dentist_review_required": True,
            "no_automatic_execution": True,
            "no_treatment_simulation": True,
            "server_renders_public_text": True,
        },
    }
    redacted = Redactor(enabled=True).redact_result(payload)
    return redacted, digest_value(redacted)


def build_provider_planning_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Return provider input with exactly one clinical-fact source: evidence[*].facts."""
    provider_payload = dict(payload)
    case = dict(payload["case"])

    case["evidence"] = {
        evidence_id: {
            "section": value.get("section"),
            "facts": value.get("facts", {}),
        }
        for evidence_id, value in payload["case"]["evidence"].items()
    }
    case["reference_frame"] = {
        key: value for key, value in payload["case"]["reference_frame"].items() if key != "data"
    }
    case["sections"] = {
        name: {key: value for key, value in section.items() if key != "data"}
        for name, section in payload["case"]["sections"].items()
    }

    provider_payload["case"] = case
    return provider_payload


__all__ = ["build_planning_llm_input", "build_provider_planning_input"]
