from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.ai_case_summary.contracts import (
    AICaseSummary,
    ModelProvenance,
    ReviewStatus,
    SummaryClaim,
    SummaryContent,
    SummaryDataGap,
    UnifiedCaseReference,
)
from app.modules.patient_presentation_mode.service import (
    PresentationNotReadyError,
    build_patient_presentation,
)


def _summary(*, status: ReviewStatus = ReviewStatus.ACCEPTED, reviewed: bool = True) -> AICaseSummary:
    reviewed_at = datetime.now(UTC) if reviewed else None
    reviewed_by = uuid4() if reviewed else None
    return AICaseSummary(
        id=uuid4(),
        patient_id=uuid4(),
        summary_version=3,
        unified_case=UnifiedCaseReference(
            case_snapshot_version=7,
            case_snapshot_contract_version="1.0",
            case_source_digest="current-digest",
        ),
        content=SummaryContent(
            claims=[
                SummaryClaim(
                    claim_id="claim-1",
                    text="Reviewed finding shown exactly as accepted.",
                    evidence_ids=["evidence-1"],
                )
            ],
            data_gaps=[
                SummaryDataGap(
                    section="imaging",
                    status="not_available",
                    reason="No current image is available.",
                )
            ],
        ),
        provenance=ModelProvenance(
            provider="test-provider",
            model="test-model",
            provider_contract_version="core.llm.Provider/1",
            prompt_version="1.0",
            input_digest="input-digest",
            output_digest="output-digest",
        ),
        review_status=status,
        clinical_output=status is ReviewStatus.ACCEPTED,
        generated_at=datetime.now(UTC),
        reviewed_at=reviewed_at,
        reviewed_by=reviewed_by,
    )


def test_patient_presentation_preserves_reviewed_claims_gaps_and_provenance() -> None:
    summary = _summary()

    presentation = build_patient_presentation(
        summary,
        current_source_digest="current-digest",
    )

    assert presentation.patient_id == summary.patient_id
    assert presentation.advisory_only is True
    assert presentation.dentist_controlled is True
    assert presentation.source_current is True
    assert presentation.claims[0].text == summary.content.claims[0].text
    assert presentation.claims[0].evidence_ids == ["evidence-1"]
    assert presentation.data_gaps[0].status == "not_available"
    assert presentation.provenance.source_summary_id == summary.id
    assert presentation.provenance.case_source_digest == "current-digest"


def test_patient_presentation_fails_closed_for_unaccepted_latest_summary() -> None:
    summary = _summary(status=ReviewStatus.PENDING_REVIEW, reviewed=False)

    with pytest.raises(PresentationNotReadyError, match="latest_summary_not_accepted"):
        build_patient_presentation(summary, current_source_digest="current-digest")


def test_patient_presentation_fails_closed_when_review_provenance_is_missing() -> None:
    summary = _summary(reviewed=False)

    with pytest.raises(PresentationNotReadyError, match="review_provenance_missing"):
        build_patient_presentation(summary, current_source_digest="current-digest")


def test_patient_presentation_fails_closed_when_accepted_summary_is_stale() -> None:
    summary = _summary()

    with pytest.raises(PresentationNotReadyError, match="accepted_summary_is_stale"):
        build_patient_presentation(summary, current_source_digest="new-digest")
