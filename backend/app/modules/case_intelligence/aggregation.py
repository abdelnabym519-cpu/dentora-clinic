"""Deterministic Case Intelligence aggregation domain service."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from .contracts import (
    AggregatedCase,
    AvailabilityStatus,
    CaseIdentity,
    CaseSection,
    EvidenceReference,
    digest_value,
)

SECTION_ORDER = (
    "patient",
    "anatomy",
    "nerve",
    "alignment",
    "cbct",
    "ios",
    "prosthetic",
    "odontogram",
    "periodontogram",
    "medical_context",
    "treatment_history",
    "timeline",
    "media",
    "implant_planning",
)


class CaseAggregator:
    """Pure aggregator: it classifies availability and never mutates inputs."""

    @staticmethod
    def aggregate(
        *,
        clinic_id: UUID,
        patient_id: UUID,
        sections: dict[str, dict[str, Any]],
    ) -> AggregatedCase:
        normalized: dict[str, CaseSection] = {}
        all_evidence: list[EvidenceReference] = []
        source_versions: dict[str, str] = {}

        for name in SECTION_ORDER:
            raw = deepcopy(sections.get(name) or {})
            status = AvailabilityStatus(raw.get("status", AvailabilityStatus.NOT_AVAILABLE))
            evidence = [
                item if isinstance(item, EvidenceReference) else EvidenceReference.model_validate(item)
                for item in raw.get("evidence", [])
            ]
            evidence.sort(
                key=lambda item: (
                    item.source_module,
                    item.source_entity,
                    item.source_record_id or "",
                    item.source_version or "",
                )
            )
            section = CaseSection(
                status=status,
                data=raw.get("data"),
                evidence=evidence,
                reason=raw.get("reason"),
            )
            normalized[name] = section
            all_evidence.extend(evidence)
            for item in evidence:
                if item.source_version is not None:
                    record_key = item.source_record_id or "singleton"
                    key = f"{item.source_module}.{item.source_entity}.{record_key}"
                    source_versions[key] = item.source_version

        all_evidence.sort(
            key=lambda item: (
                item.source_module,
                item.source_entity,
                item.source_record_id or "",
                item.source_version or "",
            )
        )
        availability = {name: normalized[name].status for name in SECTION_ORDER}
        missing = [
            name
            for name in SECTION_ORDER
            if normalized[name].status != AvailabilityStatus.AVAILABLE
        ]

        alignment = normalized["alignment"]
        if alignment.status == AvailabilityStatus.AVAILABLE:
            reference_frame = CaseSection(
                status=AvailabilityStatus.AVAILABLE,
                data=(alignment.data or {}).get("patient_space"),
                evidence=list(alignment.evidence),
            )
            if reference_frame.data is None:
                reference_frame = CaseSection(
                    status=AvailabilityStatus.INVALID_OR_STALE,
                    data=None,
                    evidence=list(alignment.evidence),
                    reason="accepted_alignment_missing_patient_space_metadata",
                )
        else:
            reference_frame = CaseSection(
                status=alignment.status,
                data=None,
                evidence=list(alignment.evidence),
                reason=alignment.reason or "accepted_patient_alignment_not_available",
            )

        digest_payload = {
            "contract_version": "1.0",
            "identity": {"clinic_id": str(clinic_id), "patient_id": str(patient_id)},
            "reference_frame": reference_frame.model_dump(mode="json"),
            "clinical_state": {
                name: normalized[name].model_dump(mode="json") for name in SECTION_ORDER
            },
            "availability": {name: availability[name].value for name in SECTION_ORDER},
            "provenance": [item.model_dump(mode="json") for item in all_evidence],
            "missing_data_report": missing,
            "source_versions": dict(sorted(source_versions.items())),
        }
        return AggregatedCase(
            identity=CaseIdentity(clinic_id=clinic_id, patient_id=patient_id),
            reference_frame=reference_frame,
            clinical_state=normalized,
            availability=availability,
            provenance=all_evidence,
            missing_data_report=missing,
            source_versions=dict(sorted(source_versions.items())),
            source_digest=digest_value(digest_payload),
        )
