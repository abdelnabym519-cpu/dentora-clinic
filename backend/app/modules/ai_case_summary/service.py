"""AI Case Summary application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.base import Provider
from app.core.llm.factory import get_default_model, get_provider
from app.modules.case_intelligence.contracts import digest_value
from app.modules.case_intelligence.service import CaseIntelligenceService
from app.modules.patients.models import Patient

from .contracts import (
    AI_CASE_SUMMARY_CONTRACT_VERSION,
    AI_CASE_SUMMARY_PROMPT_VERSION,
    AICaseSummary,
    ModelProvenance,
    ReviewStatus,
    SummaryContent,
    UnifiedCaseReference,
)
from .generator import SummaryGenerationError, generate_summary
from .models import AICaseSummaryRecord
from .privacy import build_provider_llm_input, build_redacted_llm_input

PROVIDER_CONTRACT_VERSION = "core.llm.Provider/1"


class AICaseSummaryService:
    provider_factory = staticmethod(get_provider)

    @classmethod
    async def generate(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        user_id: UUID | None,
        provider_name: str | None = None,
        model: str | None = None,
        provider: Provider | None = None,
    ) -> AICaseSummary:
        snapshot = await CaseIntelligenceService.get_current(
            db, clinic_id=clinic_id, patient_id=patient_id, user_id=user_id
        )
        llm_input, input_digest = build_redacted_llm_input(snapshot)
        provider_llm_input = build_provider_llm_input(llm_input)
        provider_name = provider_name or settings.COPILOT_PROVIDER_DEFAULT
        if model is None:
            model = get_default_model(provider_name)
        provider = provider or cls.provider_factory(provider_name)

        generated = await generate_summary(
            provider=provider,
            model=model,
            llm_input=provider_llm_input,
            max_tokens=settings.COPILOT_MAX_TOKENS,
        )
        output_payload = generated.content.model_dump(mode="json")
        output_digest = digest_value(output_payload)

        locked_patient = await db.scalar(
            select(Patient)
            .where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
            .with_for_update()
        )
        if locked_patient is None:
            raise KeyError("patient_not_found")
        latest = await db.scalar(
            select(AICaseSummaryRecord)
            .where(
                AICaseSummaryRecord.clinic_id == clinic_id,
                AICaseSummaryRecord.patient_id == patient_id,
            )
            .order_by(desc(AICaseSummaryRecord.summary_version))
            .limit(1)
        )
        version = 1 if latest is None else latest.summary_version + 1
        generated_at = datetime.now(UTC)
        row = AICaseSummaryRecord(
            clinic_id=clinic_id,
            patient_id=patient_id,
            summary_version=version,
            contract_version=AI_CASE_SUMMARY_CONTRACT_VERSION,
            case_snapshot_version=snapshot.case_snapshot_version,
            case_snapshot_contract_version=snapshot.contract_version,
            case_source_digest=snapshot.source_digest,
            provider_name=provider_name,
            model_name=model,
            provider_contract_version=PROVIDER_CONTRACT_VERSION,
            prompt_version=AI_CASE_SUMMARY_PROMPT_VERSION,
            input_digest=input_digest,
            output_digest=output_digest,
            summary_data=output_payload,
            review_status=ReviewStatus.PENDING_REVIEW.value,
            generated_at=generated_at,
            generated_by=user_id,
        )
        db.add(row)
        await db.commit()
        return cls._to_contract(row)

    @classmethod
    async def get_latest(
        cls, db: AsyncSession, *, clinic_id: UUID, patient_id: UUID
    ) -> AICaseSummary:
        row = await db.scalar(
            select(AICaseSummaryRecord)
            .where(
                AICaseSummaryRecord.clinic_id == clinic_id,
                AICaseSummaryRecord.patient_id == patient_id,
            )
            .order_by(desc(AICaseSummaryRecord.summary_version))
            .limit(1)
        )
        if row is None:
            raise KeyError("summary_not_found")
        return cls._to_contract(row)

    @classmethod
    async def review(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        summary_id: UUID,
        reviewer_id: UUID,
        reviewer_role: str,
        decision: str,
    ) -> AICaseSummary:
        if reviewer_role != "dentist":
            raise PermissionError("dentist_review_required")
        row = await db.scalar(
            select(AICaseSummaryRecord)
            .where(
                AICaseSummaryRecord.id == summary_id,
                AICaseSummaryRecord.clinic_id == clinic_id,
            )
            .with_for_update()
        )
        if row is None:
            raise KeyError("summary_not_found")
        if row.review_status != ReviewStatus.PENDING_REVIEW.value:
            raise ValueError("summary_already_reviewed")
        if decision not in {ReviewStatus.ACCEPTED.value, ReviewStatus.REJECTED.value}:
            raise ValueError("invalid_review_decision")
        row.review_status = decision
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        await db.commit()
        return cls._to_contract(row)

    @staticmethod
    def _to_contract(row: AICaseSummaryRecord) -> AICaseSummary:
        content = SummaryContent.model_validate(row.summary_data)
        return AICaseSummary(
            id=row.id,
            patient_id=row.patient_id,
            summary_version=row.summary_version,
            contract_version=row.contract_version,
            unified_case=UnifiedCaseReference(
                case_snapshot_version=row.case_snapshot_version,
                case_snapshot_contract_version=row.case_snapshot_contract_version,
                case_source_digest=row.case_source_digest,
            ),
            content=content,
            provenance=ModelProvenance(
                provider=row.provider_name,
                model=row.model_name,
                provider_contract_version=row.provider_contract_version,
                prompt_version=row.prompt_version,
                input_digest=row.input_digest,
                output_digest=row.output_digest,
            ),
            review_status=ReviewStatus(row.review_status),
            clinical_output=row.review_status == ReviewStatus.ACCEPTED.value,
            generated_at=row.generated_at,
            generated_by=row.generated_by,
            reviewed_at=row.reviewed_at,
            reviewed_by=row.reviewed_by,
        )
