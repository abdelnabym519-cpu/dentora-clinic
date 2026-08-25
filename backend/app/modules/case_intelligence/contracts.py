"""Versioned, deterministic Case Intelligence contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


CASE_SNAPSHOT_CONTRACT_VERSION = "1.0"


class AvailabilityStatus(StrEnum):
    """Explicit source availability; absence is never converted into a clinical value."""

    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    INVALID_OR_STALE = "invalid_or_stale"


class EvidenceReference(BaseModel):
    """Traceable source reference for one snapshot section."""

    model_config = ConfigDict(extra="forbid")

    source_module: str
    source_entity: str
    source_record_id: str | None = None
    source_version: str | None = None
    source_digest: str | None = None
    validation_state: str | None = None


class CaseSection(BaseModel):
    """One deterministic section with explicit availability and provenance."""

    model_config = ConfigDict(extra="forbid")

    status: AvailabilityStatus
    data: Any | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    reason: str | None = None


class CaseIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clinic_id: UUID
    patient_id: UUID


class CaseSnapshot(BaseModel):
    """Persisted unified clinical case evidence snapshot."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = CASE_SNAPSHOT_CONTRACT_VERSION
    case_snapshot_version: int
    identity: CaseIdentity
    reference_frame: CaseSection
    clinical_state: dict[str, CaseSection]
    availability: dict[str, AvailabilityStatus]
    provenance: list[EvidenceReference]
    missing_data_report: list[str]
    source_versions: dict[str, str]
    source_digest: str
    generated_at: datetime


class AggregatedCase(BaseModel):
    """Pure deterministic aggregation result before persistence metadata is attached."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = CASE_SNAPSHOT_CONTRACT_VERSION
    identity: CaseIdentity
    reference_frame: CaseSection
    clinical_state: dict[str, CaseSection]
    availability: dict[str, AvailabilityStatus]
    provenance: list[EvidenceReference]
    missing_data_report: list[str]
    source_versions: dict[str, str]
    source_digest: str


def canonical_json(value: Any) -> str:
    """Stable JSON representation used by source and snapshot digests."""

    def default(obj: Any) -> str:
        if isinstance(obj, (UUID, datetime)):
            return obj.isoformat() if isinstance(obj, datetime) else str(obj)
        raise TypeError(f"Unsupported canonical value: {type(obj)!r}")

    return json.dumps(
        value,
        default=default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
