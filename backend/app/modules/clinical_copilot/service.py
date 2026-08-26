"""Clinical Copilot application service.

The service is deliberately read-only. It consumes already materialized upstream artifacts,
checks their provenance chain, exposes missing/stale state, and only then allows an LLM to
produce evidence-cited advisory text. It never invokes upstream generators or canonical writes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.redaction import Redactor
from app.core.llm.base import Done, Provider, ProviderMessage, Role, TextBlock, TextDelta, ToolUse
from app.modules.ai_treatment_planning.models import AITreatmentPlanningRecord
from app.modules.case_intelligence.models import CaseSnapshotRecord
from app.modules.risk_engine.models import RiskResultRecord
from app.modules.treatment_simulation.models import TreatmentSimulationRecord

from .contracts import (
    AdvisoryClaim,
    ClinicalCopilotAdvisory,
    ClinicalCopilotContext,
    ClinicalCopilotProvenance,
    ClinicalStageStatus,
    StageName,
    StageState,
)
from .ports import SecondReviewReader, UnavailableSecondReviewReader

_BLOCKED_EXACT = {
    "address",
    "birth_date",
    "clinic_id",
    "date_of_birth",
    "email",
    "first_name",
    "full_name",
    "id",
    "last_name",
    "mobile",
    "name",
    "national_id",
    "nif",
    "dni",
    "patient_id",
    "phone",
    "phone_number",
    "ssn",
    "tax_id",
    "telephone",
}
_BLOCKED_FRAGMENTS = ("comment", "description_raw", "free_text", "narrative", "note")
_SAFE_DERIVED_ID_KEYS = {
    "checkpoint_id",
    "evidence_id",
    "evidence_ids",
    "evidence_refs",
    "factor_id",
    "option_id",
    "risk_factor_ids",
    "step_id",
}


class ClinicalContextInsufficientError(ValueError):
    def __init__(self, context: ClinicalCopilotContext):
        self.context = context
        super().__init__("clinical_context_insufficient")


class ClinicalCopilotOutputError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _blocked_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in _BLOCKED_EXACT
        or (lowered.endswith("_id") and lowered not in _SAFE_DERIVED_ID_KEYS)
        or any(fragment in lowered for fragment in _BLOCKED_FRAGMENTS)
    )


def _sanitize_structured(value: Any) -> Any:
    """Drop direct identifiers and unrestricted narrative before any cloud projection."""
    if isinstance(value, dict):
        return {
            str(key): _sanitize_structured(item)
            for key, item in value.items()
            if not _blocked_key(str(key))
        }
    if isinstance(value, list):
        return [_sanitize_structured(item) for item in value]
    return value


def _redact_structured(value: Any, *, redactor: Redactor | None = None) -> Any:
    """Apply the existing agent redactor after the stricter clinical allow/deny boundary."""
    active = redactor or Redactor(enabled=True)
    return active.redact_result(_sanitize_structured(value))


def _evidence_refs(payload: dict[str, Any]) -> list[str]:
    """Collect only explicit evidence aliases, never source record or workflow identifiers."""
    refs: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence_id" and item:
                    refs.add(str(item))
                elif key in {"evidence_ids", "evidence_refs"} and isinstance(item, list):
                    refs.update(str(ref) for ref in item if ref)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return sorted(refs)


def _availability_state(availability: Any, missing_report: Any) -> tuple[StageState, str | None]:
    if not isinstance(availability, dict) or not availability:
        return StageState.MISSING, "case_snapshot_availability_missing"
    values = {str(value) for value in availability.values()}
    if "invalid_or_stale" in values:
        return StageState.STALE, "case_snapshot_contains_stale_sources"
    if values != {"available"} or bool(missing_report):
        return StageState.MISSING, "case_snapshot_contains_missing_sources"
    return StageState.READY, None


class ClinicalCopilotService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        second_review_reader: SecondReviewReader | None = None,
    ) -> None:
        self.db = db
        self.second_review_reader = second_review_reader or UnavailableSecondReviewReader()

    async def build_context(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        redactor: Redactor | None = None,
    ) -> ClinicalCopilotContext:
        active_redactor = redactor or Redactor(enabled=True)
        snapshot = await self.db.scalar(
            select(CaseSnapshotRecord)
            .where(
                CaseSnapshotRecord.clinic_id == clinic_id,
                CaseSnapshotRecord.patient_id == patient_id,
            )
            .order_by(desc(CaseSnapshotRecord.snapshot_version))
            .limit(1)
        )
        risk = await self.db.scalar(
            select(RiskResultRecord)
            .where(RiskResultRecord.clinic_id == clinic_id, RiskResultRecord.patient_id == patient_id)
            .order_by(desc(RiskResultRecord.result_version))
            .limit(1)
        )
        planning = await self.db.scalar(
            select(AITreatmentPlanningRecord)
            .where(
                AITreatmentPlanningRecord.clinic_id == clinic_id,
                AITreatmentPlanningRecord.patient_id == patient_id,
            )
            .order_by(desc(AITreatmentPlanningRecord.planning_version))
            .limit(1)
        )
        simulation = await self.db.scalar(
            select(TreatmentSimulationRecord)
            .where(
                TreatmentSimulationRecord.clinic_id == clinic_id,
                TreatmentSimulationRecord.patient_id == patient_id,
            )
            .order_by(desc(TreatmentSimulationRecord.simulation_version))
            .limit(1)
        )
        second_review = await self.second_review_reader.get_latest(
            clinic_id=clinic_id, patient_id=patient_id
        )

        stages: list[ClinicalStageStatus] = []
        catalog: dict[str, dict[str, Any]] = {}

        if snapshot is None:
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.CASE_INTELLIGENCE,
                    state=StageState.MISSING,
                    reason="case_snapshot_missing",
                )
            )
        else:
            active_redactor.seed(snapshot.snapshot_data)
            snapshot_data = _redact_structured(snapshot.snapshot_data, redactor=active_redactor)
            availability = (
                snapshot_data.get("availability", {}) if isinstance(snapshot_data, dict) else {}
            )
            missing_report = (
                snapshot_data.get("missing_data_report", [])
                if isinstance(snapshot_data, dict)
                else []
            )
            state, reason = _availability_state(availability, missing_report)
            refs = _evidence_refs(snapshot_data if isinstance(snapshot_data, dict) else {})
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.CASE_INTELLIGENCE,
                    state=state,
                    artifact_id=str(snapshot.id),
                    artifact_version=snapshot.snapshot_version,
                    generated_at=snapshot.generated_at,
                    source_digest=snapshot.source_digest,
                    evidence_refs=refs,
                    reason=reason,
                )
            )
            catalog["case_intelligence"] = {
                "version": snapshot.snapshot_version,
                "source_digest": snapshot.source_digest,
                "missing_data_report": missing_report,
                "availability": availability,
                "provenance": snapshot_data.get("provenance", []),
            }

        if risk is None:
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.RISK_ENGINE,
                    state=StageState.MISSING,
                    reason="risk_result_missing",
                )
            )
        else:
            provenance_stale = snapshot is None or (
                risk.case_snapshot_version != snapshot.snapshot_version
                or risk.case_snapshot_contract_version != snapshot.contract_version
                or risk.source_digest != snapshot.source_digest
            )
            if provenance_stale:
                risk_state = StageState.STALE
                risk_reason = "risk_result_does_not_match_current_case_snapshot"
            elif risk.availability_state == "invalid_or_stale":
                risk_state = StageState.STALE
                risk_reason = "risk_context_invalid_or_stale"
            elif risk.availability_state != "available":
                risk_state = StageState.UNAVAILABLE
                risk_reason = f"risk_context_{risk.availability_state}"
            else:
                risk_state = StageState.READY
                risk_reason = None
            risk_data = _redact_structured(risk.result_data, redactor=active_redactor)
            refs = _evidence_refs(risk_data)
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.RISK_ENGINE,
                    state=risk_state,
                    artifact_id=str(risk.id),
                    artifact_version=risk.result_version,
                    generated_at=risk.generated_at,
                    source_digest=risk.result_digest,
                    evidence_refs=refs,
                    reason=risk_reason,
                )
            )
            catalog["risk_engine"] = {
                "version": risk.result_version,
                "availability_state": risk.availability_state,
                "input_digest": risk.input_digest,
                "result_digest": risk.result_digest,
                "review_status": risk.review_status,
                "result": risk_data,
            }

        planning_ready = False
        if planning is None:
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.TREATMENT_PLANNING,
                    state=StageState.MISSING,
                    reason="treatment_planning_missing",
                )
            )
        else:
            provenance_stale = snapshot is None or risk is None
            if snapshot is not None:
                provenance_stale = provenance_stale or (
                    planning.case_snapshot_version != snapshot.snapshot_version
                    or planning.case_snapshot_contract_version != snapshot.contract_version
                    or planning.case_source_digest != snapshot.source_digest
                )
            if risk is not None:
                provenance_stale = provenance_stale or (
                    planning.risk_engine_version != risk.engine_version
                    or planning.risk_policy_version != risk.policy_version
                    or planning.risk_input_digest != risk.input_digest
                    or planning.risk_result_digest != risk.result_digest
                )
            review_missing = (
                planning.review_status != "accepted"
                or planning.reviewed_at is None
                or planning.reviewed_by is None
            )
            planning_ready = not provenance_stale and not review_missing
            planning_data = _redact_structured(planning.planning_data, redactor=active_redactor)
            refs = _evidence_refs(planning_data)
            reason = None
            if provenance_stale:
                reason = "treatment_plan_provenance_is_stale"
            elif review_missing:
                reason = "treatment_planning_not_accepted_or_reviewed"
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.TREATMENT_PLANNING,
                    state=StageState.READY if planning_ready else StageState.STALE,
                    artifact_id=str(planning.id),
                    artifact_version=planning.planning_version,
                    generated_at=planning.generated_at,
                    source_digest=planning.output_digest,
                    evidence_refs=refs,
                    reason=reason,
                )
            )
            catalog["ai_treatment_planning"] = {
                "version": planning.planning_version,
                "output_digest": planning.output_digest,
                "review_status": planning.review_status,
                "reviewed_at": planning.reviewed_at,
                "plan": planning_data,
            }

        simulation_ready = False
        if simulation is None:
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.TREATMENT_SIMULATION,
                    state=StageState.MISSING,
                    reason="treatment_simulation_missing",
                )
            )
        else:
            provenance_stale = (
                snapshot is None or risk is None or planning is None or not planning_ready
            )
            if snapshot is not None:
                provenance_stale = provenance_stale or (
                    simulation.case_snapshot_version != snapshot.snapshot_version
                    or simulation.case_snapshot_contract_version != snapshot.contract_version
                    or simulation.case_source_digest != snapshot.source_digest
                )
            if risk is not None:
                provenance_stale = provenance_stale or (
                    simulation.risk_engine_version != risk.engine_version
                    or simulation.risk_policy_version != risk.policy_version
                    or simulation.risk_input_digest != risk.input_digest
                    or simulation.risk_result_digest != risk.result_digest
                )
            if planning is not None:
                provenance_stale = provenance_stale or (
                    simulation.planning_id != planning.id
                    or simulation.planning_version != planning.planning_version
                    or simulation.planning_output_digest != planning.output_digest
                    or simulation.planning_reviewed_at != planning.reviewed_at
                    or simulation.planning_reviewed_by != planning.reviewed_by
                )
            simulation_ready = not provenance_stale
            scene_data = _redact_structured(simulation.scene_data, redactor=active_redactor)
            refs = _evidence_refs(scene_data)
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.TREATMENT_SIMULATION,
                    state=StageState.READY if simulation_ready else StageState.STALE,
                    artifact_id=str(simulation.id),
                    artifact_version=simulation.simulation_version,
                    generated_at=simulation.generated_at,
                    source_digest=simulation.output_digest,
                    evidence_refs=refs,
                    reason=None
                    if simulation_ready
                    else "treatment_simulation_provenance_is_stale",
                )
            )
            catalog["treatment_simulation"] = {
                "version": simulation.simulation_version,
                "output_digest": simulation.output_digest,
                "option_id": simulation.option_id,
                "scene": scene_data,
            }

        if second_review is None:
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.AI_SECOND_REVIEW,
                    state=StageState.UNAVAILABLE,
                    reason="ai_second_review_contract_unavailable",
                )
            )
        else:
            provenance_stale = (
                simulation is None
                or not simulation_ready
                or second_review.simulation_id != str(simulation.id)
                or second_review.simulation_output_digest != simulation.output_digest
            )
            review_missing = (
                second_review.review_status != "accepted"
                or second_review.reviewed_at is None
                or not second_review.reviewed_by
            )
            second_review_ready = not provenance_stale and not review_missing
            reason = None
            if provenance_stale:
                reason = "ai_second_review_provenance_is_stale"
            elif review_missing:
                reason = "ai_second_review_not_accepted_or_reviewed"
            stages.append(
                ClinicalStageStatus(
                    stage=StageName.AI_SECOND_REVIEW,
                    state=StageState.READY if second_review_ready else StageState.STALE,
                    artifact_id=second_review.artifact_id,
                    artifact_version=second_review.version,
                    generated_at=second_review.generated_at,
                    source_digest=second_review.source_digest,
                    evidence_refs=sorted(set(second_review.evidence_refs)),
                    reason=reason,
                )
            )
            catalog["ai_second_review"] = _redact_structured(
                second_review.payload, redactor=active_redactor
            )

        missing_or_stale = [
            f"{stage.stage}:{stage.state}:{stage.reason or 'not_ready'}"
            for stage in stages
            if stage.state is not StageState.READY
        ]
        digest_payload = {
            "clinic_id": str(clinic_id),
            "patient_id": str(patient_id),
            "stages": [stage.model_dump(mode="json") for stage in stages],
            "catalog": catalog,
        }
        return ClinicalCopilotContext(
            clinic_id=clinic_id,
            patient_id=patient_id,
            stages=stages,
            missing_or_stale=missing_or_stale,
            evidence_catalog=catalog,
            input_digest=_digest(digest_payload),
            ready_for_advice=not missing_or_stale,
        )

    async def advise(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        focus: str,
        provider: Provider,
        provider_name: str,
        model: str,
        user_id: UUID,
        user_role: str,
    ) -> ClinicalCopilotAdvisory:
        if user_role != "dentist":
            raise PermissionError("dentist_control_required")

        redactor = Redactor(enabled=True)
        context = await self.build_context(
            clinic_id=clinic_id,
            patient_id=patient_id,
            redactor=redactor,
        )
        if not context.ready_for_advice:
            raise ClinicalContextInsufficientError(context)

        allowed_ids = {ref for stage in context.stages for ref in stage.evidence_refs if ref}
        provider_payload = _redact_structured(
            {
                "contract_version": context.contract_version,
                "focus": focus,
                "evidence_chain": context.evidence_catalog,
                "allowed_evidence_ids": sorted(allowed_ids),
                "missing_or_stale": context.missing_or_stale,
            },
            redactor=redactor,
        )
        system = (
            "You are Dentora Clinical Copilot. You are advisory only. Never diagnose, approve, "
            "select, prescribe, or autonomously decide treatment. Use only supplied structured "
            "evidence. Never infer missing facts. Every claim must cite one or more IDs from "
            "allowed_evidence_ids. Dentist review and control are mandatory. Return JSON only: "
            '{"claims":[{"text":"...","evidence_ids":["..."]}],"limitations":["..."]}.'
        )
        messages = [
            ProviderMessage(role=Role.USER, content=[TextBlock(text=_canonical(provider_payload))])
        ]
        messages = redactor.redact_outgoing(messages)

        chunks: list[str] = []
        async for event in provider.complete(
            system=system,
            messages=messages,
            tools=[],
            model=model,
            max_tokens=1200,
        ):
            if isinstance(event, TextDelta):
                chunks.append(event.text)
            elif isinstance(event, ToolUse):
                raise ClinicalCopilotOutputError("clinical_copilot_tool_use_forbidden")
            elif isinstance(event, Done):
                break

        try:
            raw = json.loads("".join(chunks))
            if set(raw) - {"claims", "limitations"}:
                raise ClinicalCopilotOutputError("clinical_copilot_invalid_provider_output")
            claims = [AdvisoryClaim.model_validate(item) for item in raw.get("claims", [])]
            limitations = [str(item) for item in raw.get("limitations", [])]
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise ClinicalCopilotOutputError("clinical_copilot_invalid_provider_output") from exc

        if not claims:
            raise ClinicalCopilotOutputError("clinical_copilot_claims_required")
        unsupported = {
            evidence_id
            for claim in claims
            for evidence_id in claim.evidence_ids
            if evidence_id not in allowed_ids
        }
        if unsupported:
            raise ClinicalCopilotOutputError("clinical_copilot_unsupported_evidence_reference")

        output_payload = {
            "claims": [claim.model_dump(mode="json") for claim in claims],
            "limitations": limitations,
        }
        return ClinicalCopilotAdvisory(
            patient_id=patient_id,
            claims=claims,
            limitations=limitations,
            provenance=ClinicalCopilotProvenance(
                provider=provider_name,
                model=model,
                input_digest=context.input_digest,
                output_digest=_digest(output_payload),
                upstream=context.stages,
                generated_at=datetime.now(UTC),
                generated_by=user_id,
            ),
        )
