"""Deterministic privacy boundary for CaseSnapshot -> cloud LLM input."""

from __future__ import annotations

from typing import Any

from app.core.agents.redaction import Redactor
from app.modules.case_intelligence.contracts import CaseSection, CaseSnapshot, digest_value

_BLOCKED_EXACT = {
    "id", "clinic_id", "patient_id", "date_of_birth", "first_name", "last_name",
    "full_name", "name", "email", "phone", "mobile", "telephone", "national_id",
    "dni", "nif", "tax_id", "notes", "note", "title", "description", "reaction",
    "complications", "procedure", "anesthesia_reaction_details", "displacement_notes",
    "event_data", "extra_data", "tags",
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


def _evidence_key(ref) -> tuple[str, str, str | None, str | None, str | None, str | None]:
    return (
        ref.source_module,
        ref.source_entity,
        ref.source_record_id,
        ref.source_version,
        ref.source_digest,
        ref.validation_state,
    )


def _section_payload(section: CaseSection, aliases: dict[tuple, str]) -> dict[str, Any]:
    return {
        "status": section.status.value,
        "data": _sanitize(section.data),
        "evidence_ids": [aliases[_evidence_key(ref)] for ref in section.evidence],
        "reason": section.reason,
    }


def build_redacted_llm_input(snapshot: CaseSnapshot) -> tuple[dict[str, Any], str]:
    """Return allowlisted, identifier-free structured input plus deterministic digest."""
    ordered_refs = sorted(
        snapshot.provenance,
        key=lambda ref: tuple("" if item is None else str(item) for item in _evidence_key(ref)),
    )
    aliases = {_evidence_key(ref): f"E{index:03d}" for index, ref in enumerate(ordered_refs, 1)}
    evidence = {
        aliases[_evidence_key(ref)]: {
            "source_module": ref.source_module,
            "source_entity": ref.source_entity,
            "source_version": ref.source_version,
            "validation_state": ref.validation_state,
        }
        for ref in ordered_refs
    }
    payload = {
        "input_contract_version": "1.0",
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
    payload = Redactor(enabled=True).redact_result(payload)
    return payload, digest_value(payload)


__all__ = ["build_redacted_llm_input"]
