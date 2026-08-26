"""Deterministic privacy boundary for AI Treatment Planning LLM input."""

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
    """Return identifier-free structured case + risk context and its digest."""
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
        },
    }
    redacted = Redactor(enabled=True).redact_result(payload)
    return redacted, digest_value(redacted)


__all__ = ["build_planning_llm_input"]
