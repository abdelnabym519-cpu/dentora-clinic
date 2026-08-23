"""Service-layer tests for Phase 4 nerve-detection use cases.

Covers:
- run → persist → latest (append-only history, latest wins)
- dentist review workflow (accept/reject, single decision, note)
- scene endpoint summary integration (``nerve_detection`` field)
- clinic isolation and unknown-analysis handling
- provider engine failure surfaces (never faked)
- provider injection (the service depends on the port, not the adapter)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dental_3d.models import DentalNerveAnalysis as AnalysisRow
from app.modules.dental_3d.nerve import (
    NerveDetectionRequest,
    NerveDetectionResult,
    NerveReviewUpdate,
)
from app.modules.dental_3d.service import (
    DentalNerveService,
    DentalSceneService,
    NerveError,
)
from app.modules.odontogram.models import ToothRecord
from app.modules.patients.models import Patient


class _StubProvider:
    """Deterministic stub behind the port — proves the seam is real."""

    name = "stub-nerve"
    input_kind = "scene"  # type: ignore[assignment]

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
        return NerveDetectionResult(
            provider=self.name,
            method="stub-method",
            performed_at=request.performed_at,
        )


class _FailingProvider:
    name = "boom-nerve"
    input_kind = "scene"  # type: ignore[assignment]

    async def detect(self, request: NerveDetectionRequest) -> NerveDetectionResult:
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
async def test_run_detection_persists_pending_review(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    analysis = await DentalNerveService.run_detection(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,  # FK-honest: real users come from the API layer
    )
    assert analysis.review_status == "pending"
    assert analysis.is_clinical is False
    assert analysis.requires_review is True
    assert analysis.provider == "canonical-mandible"
    assert analysis.method == "canonical-mandible-model-v0"
    assert analysis.pathway_count == 2  # left + right
    assert analysis.near_count == 4  # 37/38/47/48 on a full healthy arch
    assert analysis.watch_count == 6  # premolars + first molars
    assert len(analysis.proximities) == 16  # every present lower tooth
    assert "verify" in analysis.disclaimer.lower()
    assert "simulated" in analysis.disclaimer.lower()


@pytest.mark.asyncio
async def test_odontogram_absence_drops_proximity(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    await _seed_condition(db_session, test_patient.clinic_id, test_patient.id, 48, "missing")
    analysis = await DentalNerveService.run_detection(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    listed = {p.tooth_number for p in analysis.proximities}
    assert 48 not in listed
    assert analysis.near_count == 3  # 37, 38, 47


@pytest.mark.asyncio
async def test_latest_analysis_wins_and_history_is_append_only(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    first = await DentalNerveService.run_detection(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,
        provider=_StubProvider(),
    )
    second = await DentalNerveService.run_detection(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    latest = await DentalNerveService.latest_analysis(
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
        await DentalNerveService.latest_analysis(
            db_session, test_patient.clinic_id, test_patient.id
        )
        is None
    )


@pytest.mark.asyncio
async def test_review_accept_records_dentist_decision(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    analysis = await DentalNerveService.run_detection(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    reviewed = await DentalNerveService.review_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        analysis_id=analysis.id,
        reviewer_id=None,  # FK-honest: real reviewers come from the API layer
        payload=NerveReviewUpdate(decision="accepted", note="verified against radiograph"),
    )
    assert reviewed.review_status == "accepted"
    assert reviewed.reviewed_at is not None
    assert reviewed.review_note == "verified against radiograph"


@pytest.mark.asyncio
async def test_review_reject_and_no_double_review(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    analysis = await DentalNerveService.run_detection(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    rejected = await DentalNerveService.review_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        analysis_id=analysis.id,
        reviewer_id=None,
        payload=NerveReviewUpdate(decision="rejected"),
    )
    assert rejected.review_status == "rejected"
    with pytest.raises(NerveError):
        await DentalNerveService.review_analysis(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            analysis_id=analysis.id,
            reviewer_id=None,
            payload=NerveReviewUpdate(decision="accepted"),  # flip after decision
        )


@pytest.mark.asyncio
async def test_review_unknown_analysis_raises_key_error(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    with pytest.raises(KeyError):
        await DentalNerveService.review_analysis(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            analysis_id=uuid4(),
            reviewer_id=None,
            payload=NerveReviewUpdate(decision="accepted"),
        )


@pytest.mark.asyncio
async def test_provider_failure_surfaces_as_nerve_error(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    with pytest.raises(NerveError, match="nerve detection provider failed"):
        await DentalNerveService.run_detection(
            db_session,
            clinic_id=test_patient.clinic_id,
            patient_id=test_patient.id,
            user_id=None,
            provider=_FailingProvider(),
        )


@pytest.mark.asyncio
async def test_provider_injection_uses_the_port(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    analysis = await DentalNerveService.run_detection(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        user_id=None,
        provider=_StubProvider(),
    )
    assert analysis.provider == "stub-nerve"
    assert analysis.pathways == []  # whatever the engine returns — never faked


@pytest.mark.asyncio
async def test_scene_summary_reflects_latest_analysis(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert scene.nerve_detection.status == "not_available"

    analysis = await DentalNerveService.run_detection(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    reviewed = await DentalNerveService.review_analysis(
        db_session,
        clinic_id=test_patient.clinic_id,
        patient_id=test_patient.id,
        analysis_id=analysis.id,
        reviewer_id=None,
        payload=NerveReviewUpdate(decision="accepted"),
    )
    assert reviewed.review_status == "accepted"

    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    summary = scene.nerve_detection
    assert summary.status == "completed"
    assert summary.analysis_id == analysis.id
    assert summary.provider == "canonical-mandible"
    assert summary.pathway_count == 2
    assert summary.near_count == 4
    assert summary.watch_count == 6
    assert summary.review_status == "accepted"
    assert summary.non_clinical is True
    assert summary.performed_at is not None


@pytest.mark.asyncio
async def test_clinic_isolation(db_session: AsyncSession, test_patient: Patient) -> None:
    from app.core.auth.models import Clinic

    other = Clinic(id=uuid4(), name="Other", tax_id="B00000001", address={}, settings={})
    db_session.add(other)
    await db_session.commit()

    analysis = await DentalNerveService.run_detection(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    # Another clinic sees nothing of this patient's analyses.
    assert await DentalNerveService.latest_analysis(db_session, other.id, test_patient.id) is None
    with pytest.raises(KeyError):
        await DentalNerveService.review_analysis(
            db_session,
            clinic_id=other.id,
            patient_id=test_patient.id,
            analysis_id=analysis.id,
            reviewer_id=None,
            payload=NerveReviewUpdate(decision="accepted"),
        )


@pytest.mark.asyncio
async def test_performed_at_pinned_to_request_clock(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    """The analysis clock comes from the server request, not the provider env."""
    analysis = await DentalNerveService.run_detection(
        db_session, clinic_id=test_patient.clinic_id, patient_id=test_patient.id, user_id=None
    )
    assert analysis.performed_at.tzinfo is not None
    assert analysis.performed_at <= datetime.now(UTC)
