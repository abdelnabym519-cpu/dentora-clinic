"""Pure deterministic Risk Engine over a versioned CaseSnapshot.

The policy intentionally evaluates only explicit structured observations and
availability states. It contains no clinical thresholds, scores, diagnoses,
HU assumptions, bone-quality assumptions, or free-text inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.case_intelligence.contracts import (
    AvailabilityStatus,
    CaseSection,
    CaseSnapshot,
    EvidenceReference,
    digest_value,
)

from .contracts import (
    RISK_ENGINE_VERSION,
    RISK_POLICY_VERSION,
    RISK_RESULT_CONTRACT_VERSION,
    PatientPointMm,
    PatientVector,
    RiskDisplayBand,
    RiskEvidenceReference,
    RiskFactor,
    RiskFactorState,
    RiskMap,
    RiskMapFrame,
    RiskMapRegion,
)

RELEVANT_SECTIONS = (
    "alignment",
    "anatomy",
    "nerve",
    "medical_context",
    "odontogram",
    "periodontogram",
    "implant_planning",
)


@dataclass(frozen=True)
class RiskEvaluation:
    factors: list[RiskFactor]
    evidence: list[RiskEvidenceReference]
    risk_map: RiskMap
    input_digest: str
    result_digest: str
    availability_state: str


def _evidence_key(ref: EvidenceReference) -> tuple[str, str, str, str, str, str]:
    return (
        ref.source_module,
        ref.source_entity,
        ref.source_record_id or "",
        ref.source_version or "",
        ref.source_digest or "",
        ref.validation_state or "",
    )


def _evidence_catalog(
    snapshot: CaseSnapshot,
) -> tuple[list[RiskEvidenceReference], dict[tuple, str]]:
    unique: dict[tuple[str, str, str, str, str, str], EvidenceReference] = {}
    for ref in snapshot.provenance:
        unique[_evidence_key(ref)] = ref
    ordered = [unique[key] for key in sorted(unique)]
    result: list[RiskEvidenceReference] = []
    aliases: dict[tuple, str] = {}
    for index, ref in enumerate(ordered, start=1):
        alias = f"E{index:03d}"
        aliases[_evidence_key(ref)] = alias
        result.append(
            RiskEvidenceReference(
                evidence_id=alias,
                source_module=ref.source_module,
                source_entity=ref.source_entity,
                source_record_id=ref.source_record_id,
                source_version=ref.source_version,
                source_digest=ref.source_digest,
                validation_state=ref.validation_state,
            )
        )
    return result, aliases


def _section_evidence(section: CaseSection, aliases: dict[tuple, str]) -> list[str]:
    return sorted(
        alias for ref in section.evidence if (alias := aliases.get(_evidence_key(ref))) is not None
    )


def _band(state: RiskFactorState) -> RiskDisplayBand:
    if state == RiskFactorState.PRESENT:
        return RiskDisplayBand.EVIDENCE_PRESENT
    if state == RiskFactorState.ABSENT:
        return RiskDisplayBand.EVIDENCE_ABSENT
    if state == RiskFactorState.INVALID_OR_STALE:
        return RiskDisplayBand.INVALID_SOURCE
    return RiskDisplayBand.DATA_GAP


def _unavailable_state(section: CaseSection) -> RiskFactorState | None:
    if section.status == AvailabilityStatus.INVALID_OR_STALE:
        return RiskFactorState.INVALID_OR_STALE
    if section.status != AvailabilityStatus.AVAILABLE:
        return RiskFactorState.NOT_AVAILABLE
    return None


def _factor(
    factor_id: str,
    label: str,
    state: RiskFactorState,
    *,
    evidence_ids: list[str],
    semantics: str,
    observed_value: bool | float | int | str | None = None,
    unit: str | None = None,
) -> RiskFactor:
    return RiskFactor(
        factor_id=factor_id,
        label=label,
        state=state,
        display_band=_band(state),
        evidence_ids=evidence_ids,
        observed_value=observed_value,
        unit=unit,
        semantics=semantics,
    )


def _boolean_context_factor(
    section: CaseSection,
    aliases: dict[tuple, str],
    *,
    factor_id: str,
    field: str,
    label: str,
    semantics: str,
) -> RiskFactor:
    evidence_ids = _section_evidence(section, aliases)
    unavailable = _unavailable_state(section)
    if unavailable is not None:
        return _factor(
            factor_id,
            label,
            unavailable,
            evidence_ids=evidence_ids,
            semantics=semantics,
        )
    context = (section.data or {}).get("context")
    if not isinstance(context, dict) or context.get(field) is None:
        return _factor(
            factor_id,
            label,
            RiskFactorState.NOT_AVAILABLE,
            evidence_ids=evidence_ids,
            semantics=semantics,
        )
    value = context.get(field)
    if not isinstance(value, bool):
        return _factor(
            factor_id,
            label,
            RiskFactorState.INVALID_OR_STALE,
            evidence_ids=evidence_ids,
            semantics=semantics,
        )
    state = RiskFactorState.PRESENT if value else RiskFactorState.ABSENT
    return _factor(
        factor_id,
        label,
        state,
        evidence_ids=evidence_ids,
        semantics=semantics,
        observed_value=value,
    )


def _periodontal_boolean_factor(
    section: CaseSection,
    aliases: dict[tuple, str],
    *,
    factor_id: str,
    field: str,
    label: str,
    semantics: str,
) -> RiskFactor:
    evidence_ids = _section_evidence(section, aliases)
    unavailable = _unavailable_state(section)
    if unavailable is not None:
        return _factor(
            factor_id,
            label,
            unavailable,
            evidence_ids=evidence_ids,
            semantics=semantics,
        )
    sites = (section.data or {}).get("sites")
    if not isinstance(sites, list) or not sites:
        return _factor(
            factor_id,
            label,
            RiskFactorState.NOT_AVAILABLE,
            evidence_ids=evidence_ids,
            semantics=semantics,
        )
    values = [item.get(field) for item in sites if isinstance(item, dict) and field in item]
    if not values or any(value is not None and not isinstance(value, bool) for value in values):
        return _factor(
            factor_id,
            label,
            RiskFactorState.INVALID_OR_STALE,
            evidence_ids=evidence_ids,
            semantics=semantics,
        )
    explicit = [value for value in values if isinstance(value, bool)]
    if not explicit:
        return _factor(
            factor_id,
            label,
            RiskFactorState.NOT_AVAILABLE,
            evidence_ids=evidence_ids,
            semantics=semantics,
        )
    present = any(explicit)
    return _factor(
        factor_id,
        label,
        RiskFactorState.PRESENT if present else RiskFactorState.ABSENT,
        evidence_ids=evidence_ids,
        semantics=semantics,
        observed_value=present,
    )


def _nerve_factor(section: CaseSection, aliases: dict[tuple, str]) -> RiskFactor:
    evidence_ids = _section_evidence(section, aliases)
    unavailable = _unavailable_state(section)
    if unavailable is not None:
        return _factor(
            "accepted_nerve_pathway_present",
            "Accepted patient-space mandibular nerve pathway present",
            unavailable,
            evidence_ids=evidence_ids,
            semantics="Exact presence of a dentist-accepted detected nerve pathway in DICOM patient millimetres; not a diagnosis.",
        )
    pathways = (section.data or {}).get("pathways")
    if not isinstance(pathways, list):
        return _factor(
            "accepted_nerve_pathway_present",
            "Accepted patient-space mandibular nerve pathway present",
            RiskFactorState.INVALID_OR_STALE,
            evidence_ids=evidence_ids,
            semantics="Exact presence of a dentist-accepted detected nerve pathway in DICOM patient millimetres; not a diagnosis.",
        )
    present = bool(pathways)
    return _factor(
        "accepted_nerve_pathway_present",
        "Accepted patient-space mandibular nerve pathway present",
        RiskFactorState.PRESENT if present else RiskFactorState.ABSENT,
        evidence_ids=evidence_ids,
        semantics="Exact presence of a dentist-accepted detected nerve pathway in DICOM patient millimetres; not a diagnosis.",
        observed_value=present,
    )


def _accepted_plans(section: CaseSection) -> list[dict[str, Any]]:
    plans = (section.data or {}).get("plans")
    if not isinstance(plans, list):
        return []
    return [item for item in plans if isinstance(item, dict) and item.get("status") == "accepted"]


def _implant_factors(
    section: CaseSection,
    nerve: CaseSection,
    aliases: dict[tuple, str],
) -> tuple[RiskFactor, RiskFactor]:
    plan_evidence = _section_evidence(section, aliases)
    nerve_evidence = _section_evidence(nerve, aliases)
    unavailable = _unavailable_state(section)
    if unavailable is not None:
        plan_factor = _factor(
            "current_accepted_implant_plan_present",
            "Current accepted implant plan present",
            unavailable,
            evidence_ids=plan_evidence,
            semantics="Exact presence of an accepted current Implant Planning revision; no autonomous treatment recommendation.",
        )
        intersection_factor = _factor(
            "accepted_implant_intersects_accepted_nerve_centerline",
            "Accepted implant solid intersects accepted nerve centerline",
            unavailable,
            evidence_ids=sorted(set(plan_evidence + nerve_evidence)),
            semantics="Exact geometric intersection flag from Implant Planning. It is not canal-wall clearance and has no clinical threshold.",
        )
        return plan_factor, intersection_factor

    plans = _accepted_plans(section)
    plan_present = bool(plans)
    plan_factor = _factor(
        "current_accepted_implant_plan_present",
        "Current accepted implant plan present",
        RiskFactorState.PRESENT if plan_present else RiskFactorState.ABSENT,
        evidence_ids=plan_evidence,
        semantics="Exact presence of an accepted current Implant Planning revision; no autonomous treatment recommendation.",
        observed_value=plan_present,
    )
    if not plans:
        return plan_factor, _factor(
            "accepted_implant_intersects_accepted_nerve_centerline",
            "Accepted implant solid intersects accepted nerve centerline",
            RiskFactorState.NOT_AVAILABLE,
            evidence_ids=sorted(set(plan_evidence + nerve_evidence)),
            semantics="Exact geometric intersection flag from Implant Planning. It is not canal-wall clearance and has no clinical threshold.",
        )
    if nerve.status == AvailabilityStatus.INVALID_OR_STALE:
        state = RiskFactorState.INVALID_OR_STALE
        observed = None
    elif nerve.status != AvailabilityStatus.AVAILABLE:
        state = RiskFactorState.NOT_AVAILABLE
        observed = None
    else:
        flags: list[bool] = []
        invalid = False
        for plan in plans:
            assessment = (plan.get("revision") or {}).get("assessment") or {}
            value = assessment.get("intersects_nerve_centerline")
            if value is None:
                continue
            if not isinstance(value, bool):
                invalid = True
                break
            flags.append(value)
        if invalid:
            state = RiskFactorState.INVALID_OR_STALE
            observed = None
        elif not flags:
            state = RiskFactorState.NOT_AVAILABLE
            observed = None
        else:
            observed = any(flags)
            state = RiskFactorState.PRESENT if observed else RiskFactorState.ABSENT
    return plan_factor, _factor(
        "accepted_implant_intersects_accepted_nerve_centerline",
        "Accepted implant solid intersects accepted nerve centerline",
        state,
        evidence_ids=sorted(set(plan_evidence + nerve_evidence)),
        semantics="Exact geometric intersection flag from Implant Planning. It is not canal-wall clearance and has no clinical threshold.",
        observed_value=observed,
    )


def _frame(snapshot: CaseSnapshot) -> RiskMapFrame | None:
    if snapshot.reference_frame.status != AvailabilityStatus.AVAILABLE:
        return None
    raw = snapshot.reference_frame.data
    if not isinstance(raw, dict):
        return None
    target = raw.get("target_frame")
    if not isinstance(target, dict):
        return None
    if target.get("kind") != "dicom_patient" or target.get("unit") != "mm":
        return None
    uid = target.get("frame_of_reference_uid")
    if not isinstance(uid, str) or not uid:
        return None
    return RiskMapFrame(frame_of_reference_uid=uid)


def _point(value: Any) -> PatientPointMm | None:
    if not isinstance(value, dict):
        return None
    try:
        return PatientPointMm.model_validate(value)
    except ValueError:
        return None


def _vector(value: Any) -> PatientVector | None:
    if not isinstance(value, dict):
        return None
    try:
        return PatientVector.model_validate(value)
    except ValueError:
        return None


def _risk_map(
    snapshot: CaseSnapshot,
    factors: dict[str, RiskFactor],
    aliases: dict[tuple, str],
) -> RiskMap:
    alignment = snapshot.clinical_state["alignment"]
    anatomy = snapshot.clinical_state["anatomy"]
    nerve = snapshot.clinical_state["nerve"]
    implant = snapshot.clinical_state["implant_planning"]
    frame = _frame(snapshot)
    if frame is None:
        return RiskMap(status="unavailable", reason="accepted_patient_space_frame_not_available")
    if alignment.status != AvailabilityStatus.AVAILABLE:
        return RiskMap(status="unavailable", reason="accepted_alignment_not_available")
    if anatomy.status != AvailabilityStatus.AVAILABLE:
        return RiskMap(status="unavailable", reason="validated_anatomy_not_available")

    regions: list[RiskMapRegion] = []
    nerve_ids = _section_evidence(nerve, aliases)
    if nerve.status == AvailabilityStatus.AVAILABLE:
        for index, pathway in enumerate((nerve.data or {}).get("pathways") or []):
            if not isinstance(pathway, dict):
                continue
            reference = pathway.get("reference_space") or {}
            if (
                reference.get("kind") != "dicom_patient"
                or reference.get("unit") != "mm"
                or reference.get("frame_of_reference_uid") != frame.frame_of_reference_uid
            ):
                continue
            points = [_point(item) for item in pathway.get("points") or []]
            valid_points = [item for item in points if item is not None]
            if len(valid_points) < 2 or len(valid_points) != len(points):
                continue
            if not nerve_ids:
                continue
            regions.append(
                RiskMapRegion(
                    region_id=f"nerve-pathway-{index + 1}",
                    kind="polyline",
                    display_band=factors["accepted_nerve_pathway_present"].display_band,
                    factor_ids=["accepted_nerve_pathway_present"],
                    evidence_ids=nerve_ids,
                    points=valid_points,
                )
            )

    plan_ids = _section_evidence(implant, aliases)
    intersection = factors["accepted_implant_intersects_accepted_nerve_centerline"]
    for index, plan in enumerate(_accepted_plans(implant)):
        revision = plan.get("revision") or {}
        candidate = revision.get("candidate") or {}
        if candidate.get("frame_of_reference_uid") != frame.frame_of_reference_uid:
            continue
        if candidate.get("unit") != "mm":
            continue
        center = _point(candidate.get("center"))
        axis = _vector(candidate.get("axis"))
        diameter = candidate.get("diameter_mm")
        length = candidate.get("length_mm")
        if center is None or axis is None:
            continue
        if not isinstance(diameter, (int, float)) or not isinstance(length, (int, float)):
            continue
        if diameter <= 0 or length <= 0 or not plan_ids:
            continue
        factor_ids = ["current_accepted_implant_plan_present"]
        evidence_ids = list(plan_ids)
        display_band = factors["current_accepted_implant_plan_present"].display_band
        if intersection.state in {RiskFactorState.PRESENT, RiskFactorState.ABSENT}:
            factor_ids.append("accepted_implant_intersects_accepted_nerve_centerline")
            evidence_ids = sorted(set(evidence_ids + intersection.evidence_ids))
            display_band = intersection.display_band
        regions.append(
            RiskMapRegion(
                region_id=f"accepted-implant-{index + 1}",
                kind="cylinder",
                display_band=display_band,
                factor_ids=factor_ids,
                evidence_ids=evidence_ids,
                center=center,
                axis=axis,
                radius_mm=float(diameter) * 0.5,
                length_mm=float(length),
            )
        )

    if not regions:
        return RiskMap(status="unavailable", reason="patient_space_risk_evidence_not_available")
    return RiskMap(status="available", frame=frame, regions=regions)


def evaluate_snapshot(snapshot: CaseSnapshot) -> RiskEvaluation:
    """Evaluate one CaseSnapshot without side effects or hidden clinical inference."""

    evidence, aliases = _evidence_catalog(snapshot)
    medical = snapshot.clinical_state["medical_context"]
    periodontogram = snapshot.clinical_state["periodontogram"]
    nerve = snapshot.clinical_state["nerve"]
    implant = snapshot.clinical_state["implant_planning"]

    factors = [
        _boolean_context_factor(
            medical,
            aliases,
            factor_id="smoking_context_present",
            field="is_smoker",
            label="Structured smoking context present",
            semantics="Direct structured is_smoker observation only; no dose or outcome inference.",
        ),
        _boolean_context_factor(
            medical,
            aliases,
            factor_id="anticoagulant_context_present",
            field="is_on_anticoagulants",
            label="Structured anticoagulant context present",
            semantics="Direct structured is_on_anticoagulants observation only; no medication or bleeding-risk inference.",
        ),
        _boolean_context_factor(
            medical,
            aliases,
            factor_id="bruxism_context_present",
            field="bruxism",
            label="Structured bruxism context present",
            semantics="Direct structured bruxism observation only; no diagnostic inference.",
        ),
        _boolean_context_factor(
            medical,
            aliases,
            factor_id="adverse_anesthesia_reaction_context_present",
            field="adverse_reactions_to_anesthesia",
            label="Structured adverse anaesthesia reaction context present",
            semantics="Direct structured boolean observation only; free-text reaction details are not evaluated.",
        ),
        _periodontal_boolean_factor(
            periodontogram,
            aliases,
            factor_id="periodontal_bleeding_observed",
            field="bleeding_on_probing",
            label="Bleeding-on-probing observation present",
            semantics="Any explicit true bleeding_on_probing site in the latest closed periodontogram; no diagnostic threshold.",
        ),
        _periodontal_boolean_factor(
            periodontogram,
            aliases,
            factor_id="periodontal_plaque_observed",
            field="plaque",
            label="Plaque observation present",
            semantics="Any explicit true plaque site in the latest closed periodontogram; no diagnostic threshold.",
        ),
        _periodontal_boolean_factor(
            periodontogram,
            aliases,
            factor_id="periodontal_suppuration_observed",
            field="suppuration",
            label="Suppuration observation present",
            semantics="Any explicit true suppuration site in the latest closed periodontogram; no diagnostic threshold.",
        ),
        _nerve_factor(nerve, aliases),
    ]
    plan_factor, intersection_factor = _implant_factors(implant, nerve, aliases)
    factors.extend([plan_factor, intersection_factor])
    factors.sort(key=lambda item: item.factor_id)
    factor_index = {item.factor_id: item for item in factors}
    risk_map = _risk_map(snapshot, factor_index, aliases)

    relevant_projection = {
        name: snapshot.clinical_state[name].model_dump(mode="json") for name in RELEVANT_SECTIONS
    }
    input_payload = {
        "contract_version": RISK_RESULT_CONTRACT_VERSION,
        "engine_version": RISK_ENGINE_VERSION,
        "policy_version": RISK_POLICY_VERSION,
        "case_snapshot_version": snapshot.case_snapshot_version,
        "case_snapshot_contract_version": snapshot.contract_version,
        "case_source_digest": snapshot.source_digest,
        "reference_frame": snapshot.reference_frame.model_dump(mode="json"),
        "sections": relevant_projection,
    }
    input_digest = digest_value(input_payload)
    result_payload = {
        "contract_version": RISK_RESULT_CONTRACT_VERSION,
        "engine_version": RISK_ENGINE_VERSION,
        "policy_version": RISK_POLICY_VERSION,
        "input_digest": input_digest,
        "factors": [item.model_dump(mode="json") for item in factors],
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "risk_map": risk_map.model_dump(mode="json"),
    }
    result_digest = digest_value(result_payload)

    states = {item.state for item in factors}
    if RiskFactorState.INVALID_OR_STALE in states:
        availability_state = "invalid_or_stale"
    elif states and states <= {RiskFactorState.NOT_AVAILABLE}:
        availability_state = "unavailable"
    elif RiskFactorState.NOT_AVAILABLE in states:
        availability_state = "partial"
    else:
        availability_state = "available"
    return RiskEvaluation(
        factors=factors,
        evidence=evidence,
        risk_map=risk_map,
        input_digest=input_digest,
        result_digest=result_digest,
        availability_state=availability_state,
    )


__all__ = ["RiskEvaluation", "evaluate_snapshot"]
