"""Read-only Patient Presentation application service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_case_summary.contracts import AICaseSummary, ReviewStatus
from app.modules.ai_case_summary.service import AICaseSummaryService
from app.modules.case_intelligence.aggregation import CaseAggregator
from app.modules.case_intelligence.service import CaseIntelligenceService

from .contracts import (
    PatientPresentation,
    PresentationClaim,
    PresentationDataGap,
    PresentationProvenance,
)


class PresentationNotReadyError(ValueError):
    """The requested presentation cannot be shown safely yet."""


def build_patient_presentation(
    summary: AICaseSummary, *, current_source_digest: str
) -> PatientPresentation:
    """Create an ephemeral projection without changing or inventing clinical facts."""
    if summary.review_status is not ReviewStatus.ACCEPTED or not summary.clinical_output:
        raise PresentationNotReadyError("latest_summary_not_accepted")
    if summary.reviewed_at is None or summary.reviewed_by is None:
        raise PresentationNotReadyError("review_provenance_missing")
    if not summary.unified_case.case_source_digest:
        raise PresentationNotReadyError("case_provenance_missing")
    if current_source_digest != summary.unified_case.case_source_digest:
        raise PresentationNotReadyError("accepted_summary_is_stale")

    claims: list[PresentationClaim] = []
    for claim in summary.content.claims:
        if not claim.evidence_ids:
            raise PresentationNotReadyError("claim_evidence_missing")
        claims.append(
            PresentationClaim(
                claim_id=claim.claim_id,
                text=claim.text,
                evidence_ids=list(claim.evidence_ids),
            )
        )

    gaps = [
        PresentationDataGap(section=gap.section, status=gap.status, reason=gap.reason)
        for gap in summary.content.data_gaps
    ]
    return PatientPresentation(
        patient_id=summary.patient_id,
        claims=claims,
        data_gaps=gaps,
        provenance=PresentationProvenance(
            source_summary_id=summary.id,
            source_summary_version=summary.summary_version,
            case_snapshot_version=summary.unified_case.case_snapshot_version,
            case_snapshot_contract_version=summary.unified_case.case_snapshot_contract_version,
            case_source_digest=summary.unified_case.case_source_digest,
            reviewed_at=summary.reviewed_at,
            reviewed_by=summary.reviewed_by,
            provider=summary.provenance.provider,
            model=summary.provenance.model,
            input_digest=summary.provenance.input_digest,
            output_digest=summary.provenance.output_digest,
        ),
    )


class PatientPresentationService:
    @classmethod
    async def get_current(
        cls,
        db: AsyncSession,
        *,
        clinic_id: UUID,
        patient_id: UUID,
    ) -> PatientPresentation:
        summary = await AICaseSummaryService.get_latest(
            db, clinic_id=clinic_id, patient_id=patient_id
        )

        # Re-read authoritative sources without materializing a new CaseSnapshot.
        # This makes stale accepted output fail closed while keeping the mode read-only.
        sections = await CaseIntelligenceService.provider.collect(
            db,
            clinic_id=clinic_id,
            patient_id=patient_id,
        )
        current = CaseAggregator.aggregate(
            clinic_id=clinic_id,
            patient_id=patient_id,
            sections=sections,
        )
        return build_patient_presentation(
            summary,
            current_source_digest=current.source_digest,
        )
