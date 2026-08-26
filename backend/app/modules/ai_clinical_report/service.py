"""Application service for fail-closed, draft-only AI Clinical Reports."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.base import Provider
from app.modules.ai_second_review.models import AISecondReviewRecord
from app.modules.clinical_copilot.contracts import (
    AdvisoryClaim,
    ClinicalCopilotAdvisory,
    ClinicalCopilotFocus,
    ClinicalStageStatus,
    StageName,
)
from app.modules.clinical_copilot.guarded import ClinicalCopilotGuardedService
from app.modules.clinical_copilot.ports import SecondReviewArtifact, SecondReviewReader

from .contracts import (
    AIClinicalReport,
    AIClinicalReportProvenance,
    AIClinicalReportReadiness,
    AIClinicalReportSection,
    ReportSectionName,
)

_REQUIRED_STAGES = (
    StageName.CASE_INTELLIGENCE,
    StageName.RISK_ENGINE,
    StageName.TREATMENT_PLANNING,
    StageName.TREATMENT_SIMULATION,
    StageName.AI_SECOND_REVIEW,
)
_SECTION_BY_STAGE = {
    StageName.CASE_INTELLIGENCE: ReportSectionName.CASE_INTELLIGENCE,
    StageName.RISK_ENGINE: ReportSectionName.RISK_ENGINE,
    StageName.TREATMENT_PLANNING: ReportSectionName.TREATMENT_PLANNING,
    StageName.TREATMENT_SIMULATION: ReportSectionName.TREATMENT_SIMULATION,
    StageName.AI_SECOND_REVIEW: ReportSectionName.AI_SECOND_REVIEW,
}


class ClinicalReportAssemblyError(ValueError):
    """Raised when an advisory cannot be assembled without inventing report content."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _evidence_refs(payload: Any) -> list[str]:
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


class DatabaseSecondReviewReader(SecondReviewReader):
    """Read-only adapter from the existing AI Second Review persistence contract."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_latest(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> SecondReviewArtifact | None:
        record = await self.db.scalar(
            select(AISecondReviewRecord)
            .where(
                AISecondReviewRecord.clinic_id == clinic_id,
                AISecondReviewRecord.patient_id == patient_id,
            )
            .order_by(desc(AISecondReviewRecord.review_version))
            .limit(1)
        )
        if record is None:
            return None
        return SecondReviewArtifact(
            artifact_id=str(record.id),
            version=record.review_version,
            generated_at=record.generated_at,
            source_digest=record.output_digest,
            simulation_id=str(record.simulation_id),
            simulation_output_digest=record.simulation_output_digest,
            review_status=record.review_status,
            reviewed_at=record.reviewed_at,
            reviewed_by=record.reviewed_by,
            evidence_refs=_evidence_refs(record.review_data),
            payload=record.review_data,
        )


def _claim_section(
    claim: AdvisoryClaim,
    upstream: list[ClinicalStageStatus],
) -> ReportSectionName:
    evidence_ids = set(claim.evidence_ids)
    matched = {
        stage.stage
        for stage in upstream
        if evidence_ids.intersection(stage.evidence_refs)
    }
    if not matched:
        raise ClinicalReportAssemblyError("ai_clinical_report_ungrounded_claim")
    if len(matched) > 1:
        return ReportSectionName.CROSS_STAGE
    return _SECTION_BY_STAGE[next(iter(matched))]


def assemble_report(advisory: ClinicalCopilotAdvisory) -> AIClinicalReport:
    """Deterministically organize validated advisory claims without generating new facts."""
    upstream_by_stage = {stage.stage: stage for stage in advisory.provenance.upstream}
    missing_stages = set(_REQUIRED_STAGES) - upstream_by_stage.keys()
    if missing_stages:
        raise ClinicalReportAssemblyError("ai_clinical_report_upstream_stage_missing")

    grouped: dict[ReportSectionName, list[AdvisoryClaim]] = defaultdict(list)
    for claim in advisory.claims:
        grouped[_claim_section(claim, advisory.provenance.upstream)].append(claim)

    sections = [
        AIClinicalReportSection(
            section=_SECTION_BY_STAGE[stage_name],
            state=upstream_by_stage[stage_name].state,
            evidence_refs=upstream_by_stage[stage_name].evidence_refs,
            claims=grouped.get(_SECTION_BY_STAGE[stage_name], []),
        )
        for stage_name in _REQUIRED_STAGES
    ]
    cross_stage_claims = grouped.get(ReportSectionName.CROSS_STAGE, [])
    if cross_stage_claims:
        sections.append(
            AIClinicalReportSection(
                section=ReportSectionName.CROSS_STAGE,
                evidence_refs=sorted(
                    {ref for claim in cross_stage_claims for ref in claim.evidence_ids}
                ),
                claims=cross_stage_claims,
            )
        )

    report_payload = {
        "patient_id": str(advisory.patient_id),
        "sections": [section.model_dump(mode="json") for section in sections],
        "limitations": advisory.limitations,
        "status": "draft",
    }
    return AIClinicalReport(
        patient_id=advisory.patient_id,
        sections=sections,
        limitations=advisory.limitations,
        provenance=AIClinicalReportProvenance(
            provider=advisory.provenance.provider,
            model=advisory.provenance.model,
            source_advisory_input_digest=advisory.provenance.input_digest,
            source_advisory_output_digest=advisory.provenance.output_digest,
            report_output_digest=_digest(report_payload),
            upstream=advisory.provenance.upstream,
            generated_at=advisory.provenance.generated_at,
            generated_by=advisory.provenance.generated_by,
        ),
    )


class AIClinicalReportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _copilot(self) -> ClinicalCopilotGuardedService:
        return ClinicalCopilotGuardedService(
            self.db,
            second_review_reader=DatabaseSecondReviewReader(self.db),
        )

    async def readiness(
        self, *, clinic_id: UUID, patient_id: UUID
    ) -> AIClinicalReportReadiness:
        context = await self._copilot().build_context(
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        return AIClinicalReportReadiness(
            patient_id=patient_id,
            ready_for_report=context.ready_for_advice,
            stages=context.stages,
            missing_or_stale=context.missing_or_stale,
            input_digest=context.input_digest,
        )

    async def generate(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        provider: Provider,
        provider_name: str,
        model: str,
        user_id: UUID,
        user_role: str,
    ) -> AIClinicalReport:
        if user_role != "dentist":
            raise PermissionError("dentist_control_required")
        advisory = await self._copilot().advise(
            clinic_id=clinic_id,
            patient_id=patient_id,
            focus=ClinicalCopilotFocus.CASE_REVIEW,
            provider=provider,
            provider_name=provider_name,
            model=model,
            user_id=user_id,
            user_role=user_role,
        )
        return assemble_report(advisory)
