"""Deterministic privacy boundary for CaseSnapshot -> cloud LLM input."""

from __future__ import annotations

from typing import Any

from app.core.agents.redaction import Redactor
from app.modules.case_intelligence.contracts import CaseSection, CaseSnapshot, digest_value

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
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if not _blocked_key(key)
        }
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


def _find_record_by_id(value: Any, record_id: str | None) -> dict[str, Any] | None:
    """Find the exact structured record represented by one evidence reference."""

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
    """Build a record-local fact projection for every groundable evidence alias."""

    result: dict[str, dict[str, Any]] = {}
    single_evidence = len(section.evidence) == 1

    for ref in section.evidence:
        alias = aliases[_evidence_key(ref)]
        matched = _find_record_by_id(section.data, ref.source_record_id)

        if matched is not None:
            facts = _sanitize(matched)
        elif single_evidence and isinstance(section.data, dict):
            # Safe fallback for singleton sections whose source record id is not
            # duplicated inside the section payload.
            facts = _sanitize(section.data)
        else:
            facts = {}

        result[alias] = {
            "section": section_name,
            "facts": facts,
        }

    return result


def build_redacted_llm_input(snapshot: CaseSnapshot) -> tuple[dict[str, Any], str]:
    """Return allowlisted, identifier-free structured input plus deterministic digest."""

    ordered_refs = sorted(
        snapshot.provenance,
        key=lambda ref: tuple(
            "" if item is None else str(item)
            for item in _evidence_key(ref)
        ),
    )
    aliases = {
        _evidence_key(ref): f"E{index:03d}"
        for index, ref in enumerate(ordered_refs, 1)
    }

    evidence = {
        aliases[_evidence_key(ref)]: {
            "source_module": ref.source_module,
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
            name: status.value
            for name, status in sorted(snapshot.availability.items())
        },
        "missing_data_report": sorted(snapshot.missing_data_report),
        "evidence": evidence,
    }

    payload = Redactor(enabled=True).redact_result(payload)
    return payload, digest_value(payload)


def build_provider_llm_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Return provider-facing record-local facts without parallel clinical data."""

    provider_payload = dict(payload)

    provider_payload["evidence"] = {
        evidence_id: {
            "section": value.get("section"),
            "facts": value.get("facts", {}),
        }
        for evidence_id, value in payload["evidence"].items()
    }

    # The provider must have exactly one source of clinical facts:
    # evidence[*].facts. Section data is intentionally removed so a model
    # cannot combine a fact path from one section with an unrelated evidence id.
    provider_payload["reference_frame"] = {
        key: value
        for key, value in payload["reference_frame"].items()
        if key != "data"
    }
    provider_payload["sections"] = {
        name: {
            key: value
            for key, value in section.items()
            if key != "data"
        }
        for name, section in payload["sections"].items()
    }

    return provider_payload


__all__ = ["build_provider_llm_input", "build_redacted_llm_input"]
