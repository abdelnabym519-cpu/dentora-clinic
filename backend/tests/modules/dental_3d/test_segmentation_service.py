"""Service-layer tests for Phase 3 segmentation use cases.

Covers:
- run → persist → latest (append-only history, latest wins)
- dentist review workflow (accept/reject, single decision, note)
- scene endpoint summary integration (``segmentation`` field)
- clinic isolation and unknown-analysis handling
- provider engine failure surfaces (never faked)
- provider injection (the service depends on the port, not the adapter)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.dental_3d.models import DentalSegmentationAnalysis as AnalysisRow
from app.modules.dental_3d.segmentation import (
    SegmentationAnalysisResult,
    SegmentationRequest,
    SegmentationReviewUpdate,
)
from app.modules.dental_3d.service import (
    DentalSceneService,
    DentalSegmentationService,
    SegmentationError,
)
from app.modules.odontogram.models import ToothRecord
from app.modules.patients.models import Patient


class _StubProvider:
    """Deterministic stub behind the port — proves the seam is real."""

    name = "stub"
    input_kind = "scene"  # type: ignore[assignment]

    async def segment(self, request: SegmentationRequest) -> SegmentationAnalysisResult:
        return SegmentationAnalysisResult(
            provider=self.name,
            method="stub-method",
            teeth=[
                {
                    "tooth_number": 11,
                    "status": "segmented",
                    "confidence": 0.8,
                    "evidence": {"basis": "arch_position", "arch_region": "Q1-incisor"},
                }
            ],
            performed_at=request.performed_at,
        )


class _FailingProvider:
    name = "boom"
    input_kind = "scene"  # type: ignore[assignment]

    async def segment(self, request: SegmentationRequest) -> SegmentationAnalysisResult:
        raise RuntimeError("engine exploded")


async def _seed_condition(
    db: AsyncSession, clinic_id, patient_id, number: int, condition: str
) -> None:
    db.add(
        ToothRecord(
            id=uuid4(),
            clinic_id=clinic_id,
            patient_id=patient_id,
            tooth_number=number,
            tooth_type="deciduous" if number >= 51 else "permanent",
            general_condition=condition,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_run_analysis_persists_pending_review(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    analysis = await DentalSegmentationService.run_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,  # FK-honest: real users come from the API layer
    )
    assert analysis.review_status == "pending"
    assert analysis.is_clinical is False
    assert analysis.requires_review is True
    assert analysis.provider == "arch-partition"
    assert analysis.segmented_count == 32  # full healthy permanent dentition
    assert analysis.uncertain_count == 0
    assert analysis.missing_count == 0
    assert analysis.teeth[0].tooth_number == 11  # stable FDI order


@pytest.mark.asyncio
async def test_odontogram_conditions_drive_statuses(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    await _seed_condition(db_session, test_patient.clinic_id, test_patient.id, 16, "crown")
    await _seed_condition(db_session, test_patient.clinic_id, test_patient.id, 46, "missing")
    analysis = await DentalSegmentationService.run_analysis(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    by_number = {t.tooth_number: t for t in analysis.teeth}
    assert by_number[16].status == "uncertain"
    assert by_number[46].status == "missing"
    assert analysis.uncertain_count == 1
    assert analysis.missing_count == 1


@pytest.mark.asyncio
async def test_latest_analysis_wins_and_history_is_append_only(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    first = await DentalSegmentationService.run_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,
        provider=_StubProvider(),
    )
    await _seed_condition(db_session, test_patient.clinic_id, test_patient.id, 21, "caries")
    second = await DentalSegmentationService.run_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,
    )
    latest = await DentalSegmentationService.latest_analysis(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert latest is not None
    assert latest.id == second.id != first.id
    rows = (await db_session.execute(select(AnalysisRow))).scalars().all()
    assert len(rows) == 2  # history preserved


@pytest.mark.asyncio
async def test_latest_analysis_none_when_never_run(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    assert (
        await DentalSegmentationService.latest_analysis(
            db_session, test_patient.clinic_id, test_patient.id
        )
        is None
    )


@pytest.mark.asyncio
async def test_review_accept_records_dentist_decision(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    analysis = await DentalSegmentationService.run_analysis(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    reviewed = await DentalSegmentationService.review_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        analysis_id=analysis.id,
        reviewer_id=None,  # FK-honest: real reviewers come from the API layer
        payload=SegmentationReviewUpdate(decision="accepted", note="checked against chart"),
    )
    assert reviewed.review_status == "accepted"
    assert reviewed.reviewed_at is not None
    assert reviewed.review_note == "checked against chart"


@pytest.mark.asyncio
async def test_review_reject_and_no_double_review(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    analysis = await DentalSegmentationService.run_analysis(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    rejected = await DentalSegmentationService.review_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        analysis_id=analysis.id,
        reviewer_id=None,
        payload=SegmentationReviewUpdate(decision="rejected"),
    )
    assert rejected.review_status == "rejected"
    with pytest.raises(SegmentationError):
        await DentalSegmentationService.review_analysis(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            analysis_id=analysis.id,
            reviewer_id=None,
            payload=SegmentationReviewUpdate(decision="accepted"),
        )


@pytest.mark.asyncio
async def test_review_unknown_analysis_raises_key_error(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    with pytest.raises(KeyError):
        await DentalSegmentationService.review_analysis(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            analysis_id=uuid4(),
            reviewer_id=None,
            payload=SegmentationReviewUpdate(decision="accepted"),
        )


@pytest.mark.asyncio
async def test_scene_summary_reflects_latest_analysis(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert scene.segmentation.status == "not_available"

    analysis = await DentalSegmentationService.run_analysis(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert scene.segmentation.status == "completed"
    assert scene.segmentation.analysis_id == analysis.id
    assert scene.segmentation.provider == "arch-partition"
    assert scene.segmentation.review_status == "pending"
    assert scene.segmentation.segmented_count == 32
    assert scene.segmentation.non_clinical is True
    # The scene itself is untouched: synthetic fallback + full dentition.
    assert scene.generator == "synthetic"
    assert len(scene.teeth) == 32


@pytest.mark.asyncio
async def test_clinic_isolation_on_run_and_review(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    other = Clinic(id=uuid4(), name="Other", tax_id="B00000001", address={}, settings={})
    db_session.add(other)
    await db_session.commit()

    # Analyses are clinic-scoped: running under another clinic creates an
    # isolated row; the test clinic never sees it.
    foreign = await DentalSegmentationService.run_analysis(
        db_session, clinic_id=other.id, patient_id=test_patient.id, user_id=None
    )
    latest_own = await DentalSegmentationService.latest_analysis(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert latest_own is None

    # Reviewing another clinic's analysis through this clinic → KeyError.
    with pytest.raises(KeyError):
        await DentalSegmentationService.review_analysis(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            analysis_id=foreign.id,
            reviewer_id=None,
            payload=SegmentationReviewUpdate(decision="accepted"),
        )


@pytest.mark.asyncio
async def test_provider_failure_surfaces_as_error(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    with pytest.raises(SegmentationError, match="provider failed"):
        await DentalSegmentationService.run_analysis(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            user_id=None,
            provider=_FailingProvider(),
        )


@pytest.mark.asyncio
async def test_provider_injection_seam(db_session: AsyncSession, test_patient: Patient) -> None:
    analysis = await DentalSegmentationService.run_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,
        provider=_StubProvider(),
    )
    assert analysis.provider == "stub"
    assert [t.tooth_number for t in analysis.teeth] == [11]
