"""Deterministic longitudinal change detection over Case Intelligence snapshots."""

from __future__ import annotations

from numbers import Real
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CHANGE_DETECTION_CONTRACT_VERSION = "1.0"

_NON_CLINICAL_KEYS = {
    "id",
    "created_at",
    "updated_at",
    "generated_at",
    "uploaded_at",
    "latest_uploaded_at",
    "performed_at",
    "reviewed_at",
    "source_digest",
    "source_version",
    "algorithm_version",
}


class ChangeDetectionRequest(BaseModel):
    """Identify two immutable Case Intelligence versions to compare."""

    model_config = ConfigDict(extra="forbid")

    baseline_version: int = Field(ge=1)
    followup_version: int = Field(ge=1)


class ChangeItem(BaseModel):
    """One traceable structured difference between two snapshots."""

    model_config = ConfigDict(extra="forbid")

    section: str
    path: str
    kind: Literal["numeric", "categorical", "availability", "added", "removed"]
    before: Any | None = None
    after: Any | None = None
    delta: float | None = None
    percent_change: float | None = None


class SnapshotEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    source_digest: str
    source_versions: dict[str, str]


class ChangeDetectionResponse(BaseModel):
    """Non-diagnostic comparison contract requiring clinician review."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = CHANGE_DETECTION_CONTRACT_VERSION
    patient_id: UUID
    baseline: SnapshotEvidence
    followup: SnapshotEvidence
    reference_frame_uid: str
    changed_sections: list[str]
    change_count: int
    changes: list[ChangeItem]
    clinician_review_required: bool = True
    informational_only: bool = True
    warnings: list[str] = Field(
        default_factory=lambda: [
            "Structured longitudinal differences are decision support, not a diagnosis.",
            "Clinical interpretation and confirmation remain the clinician's responsibility.",
        ]
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _append_change(
    changes: list[ChangeItem],
    *,
    section: str,
    path: str,
    before: Any,
    after: Any,
) -> None:
    if _is_number(before) and _is_number(after):
        before_value = float(before)
        after_value = float(after)
        delta = after_value - before_value
        percent = None
        if before_value != 0:
            percent = round((delta / abs(before_value)) * 100.0, 1)
        changes.append(
            ChangeItem(
                section=section,
                path=path,
                kind="numeric",
                before=before,
                after=after,
                delta=delta,
                percent_change=percent,
            )
        )
        return

    kind: Literal["categorical", "added", "removed"]
    if before is None:
        kind = "added"
    elif after is None:
        kind = "removed"
    else:
        kind = "categorical"
    changes.append(
        ChangeItem(
            section=section,
            path=path,
            kind=kind,
            before=before,
            after=after,
        )
    )


def _walk(
    changes: list[ChangeItem],
    *,
    section: str,
    path: str,
    before: Any,
    after: Any,
) -> None:
    if before == after:
        return

    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            if key in _NON_CLINICAL_KEYS:
                continue
            child = f"{path}.{key}" if path else key
            _walk(
                changes,
                section=section,
                path=child,
                before=before.get(key),
                after=after.get(key),
            )
        return

    if isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            child = f"{path}[{index}]"
            _walk(
                changes,
                section=section,
                path=child,
                before=before[index] if index < len(before) else None,
                after=after[index] if index < len(after) else None,
            )
        return

    _append_change(
        changes,
        section=section,
        path=path,
        before=before,
        after=after,
    )


def _reference_frame_uid(payload: dict[str, Any]) -> str:
    frame = payload.get("reference_frame") or {}
    data = frame.get("data") or {}
    if frame.get("status") != "available":
        raise ValueError("accepted longitudinal registration is required")
    if data.get("kind") != "dicom_patient" or data.get("unit") != "mm":
        raise ValueError("reference frame is not validated DICOM patient-space millimetres")
    frame_uid = data.get("frame_of_reference_uid")
    if not isinstance(frame_uid, str) or not frame_uid:
        raise ValueError("reference frame UID is missing")
    return frame_uid


def compare_snapshot_payloads(
    baseline: dict[str, Any],
    followup: dict[str, Any],
) -> tuple[str, list[ChangeItem]]:
    """Pure comparison: only structured clinical data, never provenance timestamps."""

    baseline_uid = _reference_frame_uid(baseline)
    followup_uid = _reference_frame_uid(followup)
    if baseline_uid != followup_uid:
        raise ValueError("timepoints are not registered into the same patient reference frame")

    before_state = baseline.get("clinical_state") or {}
    after_state = followup.get("clinical_state") or {}
    changes: list[ChangeItem] = []

    for section in sorted(set(before_state) | set(after_state)):
        before_section = before_state.get(section) or {}
        after_section = after_state.get(section) or {}
        before_status = before_section.get("status", "not_available")
        after_status = after_section.get("status", "not_available")
        if before_status != after_status:
            changes.append(
                ChangeItem(
                    section=section,
                    path=f"clinical_state.{section}.status",
                    kind="availability",
                    before=before_status,
                    after=after_status,
                )
            )
            continue
        if before_status != "available":
            continue
        _walk(
            changes,
            section=section,
            path=f"clinical_state.{section}.data",
            before=before_section.get("data"),
            after=after_section.get("data"),
        )

    changes.sort(key=lambda item: (item.section, item.path, item.kind))
    return baseline_uid, changes


def build_change_detection_response(
    *,
    patient_id: UUID,
    baseline_version: int,
    followup_version: int,
    baseline_payload: dict[str, Any],
    followup_payload: dict[str, Any],
    baseline_source_digest: str,
    followup_source_digest: str,
    baseline_source_versions: dict[str, str],
    followup_source_versions: dict[str, str],
) -> ChangeDetectionResponse:
    """Build a response from immutable snapshots supplied by their owning module."""

    if followup_version <= baseline_version:
        raise ValueError("followup_version must be greater than baseline_version")

    frame_uid, changes = compare_snapshot_payloads(baseline_payload, followup_payload)
    changed_sections = sorted({item.section for item in changes})
    return ChangeDetectionResponse(
        patient_id=patient_id,
        baseline=SnapshotEvidence(
            version=baseline_version,
            source_digest=baseline_source_digest,
            source_versions=baseline_source_versions,
        ),
        followup=SnapshotEvidence(
            version=followup_version,
            source_digest=followup_source_digest,
            source_versions=followup_source_versions,
        ),
        reference_frame_uid=frame_uid,
        changed_sections=changed_sections,
        change_count=len(changes),
        changes=changes,
    )
