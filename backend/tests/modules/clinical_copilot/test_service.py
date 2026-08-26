from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.llm.base import Done, TextDelta, ToolUse
from app.modules.clinical_copilot.contracts import StageName, StageState
from app.modules.clinical_copilot.ports import SecondReviewArtifact
from app.modules.clinical_copilot.service import (
    ClinicalContextInsufficient,
    ClinicalCopilotOutputError,
    ClinicalCopilotService,
    _redact_structured,
)


class FakeDB:
    def __init__(self, rows):
        self.rows = list(rows)

    async def scalar(self, _statement):
        return self.rows.pop(0)


class ReviewReader:
    def __init__(self, artifact):
        self.artifact = artifact

    async def get_latest(self, *, clinic_id, patient_id):
        return self.artifact


class FakeProvider:
    def __init__(self, payload, *, tool_use=False):
        self.payload = payload
        self.tool_use = tool_use
        self.last_user_text = None

    def complete(self, *, system, messages, tools, model, max_tokens):
        self.last_user_text = messages[0].content[0].text

        async def stream():
            if self.tool_use:
                yield ToolUse(id="call-1", name="write_record", input={})
                return
            yield TextDelta(text=json.dumps(self.payload))
            yield Done(stop_reason="stop")

        return stream()


def _chain(*, second_review=True, stale_risk=False):
    clinic_id = uuid4()
    patient_id = uuid4()
    now = datetime.now(UTC)
    snapshot_id = uuid4()
    planning_id = uuid4()
    simulation_id = uuid4()
    source_digest = "sha256:" + "1" * 64
    risk_input = "sha256:" + "2" * 64
    risk_output = "sha256:" + "3" * 64
    planning_output = "sha256:" + "4" * 64
    simulation_output = "sha256:" + "5" * 64

    snapshot = SimpleNamespace(
        id=snapshot_id,
        snapshot_version=4,
        generated_at=now,
        source_digest=source_digest,
        snapshot_data={
            "availability": {"cbct": "available"},
            "missing_data_report": [],
            "provenance": [{"source_record_id": "CASE-1"}],
            "patient": {"name": "Must not leave Dentora", "notes": "private note"},
        },
    )
    risk = SimpleNamespace(
        id=uuid4(),
        result_version=2,
        generated_at=now,
        case_snapshot_version=4,
        source_digest=("sha256:" + "9" * 64) if stale_risk else source_digest,
        input_digest=risk_input,
        result_digest=risk_output,
        availability_state="available",
        review_status="pending_review",
        result_data={"evidence": [{"evidence_id": "RISK-1"}], "notes": "drop me"},
    )
    planning = SimpleNamespace(
        id=planning_id,
        planning_version=3,
        generated_at=now,
        case_snapshot_version=4,
        case_source_digest=source_digest,
        risk_input_digest=risk_input,
        risk_result_digest=risk_output,
        output_digest=planning_output,
        review_status="accepted",
        reviewed_at=now,
        planning_data={"options": [{"option_id": "OPTION-1", "evidence_ids": ["RISK-1"]}]},
    )
    simulation = SimpleNamespace(
        id=simulation_id,
        simulation_version=1,
        generated_at=now,
        case_snapshot_version=4,
        case_source_digest=source_digest,
        risk_input_digest=risk_input,
        risk_result_digest=risk_output,
        planning_id=planning_id,
        planning_output_digest=planning_output,
        output_digest=simulation_output,
        option_id="OPTION-1",
        scene_data={"evidence_ids": ["SIM-1"], "predicted_outcome": False},
    )
    review = None
    if second_review:
        review = SecondReviewArtifact(
            artifact_id="review-1",
            version=1,
            generated_at=now,
            source_digest="sha256:" + "6" * 64,
            simulation_id=str(simulation_id),
            simulation_output_digest=simulation_output,
            evidence_refs=["REVIEW-1"],
            payload={"status": "reviewed", "evidence_ids": ["REVIEW-1"]},
        )
    return clinic_id, patient_id, [snapshot, risk, planning, simulation], review


@pytest.mark.asyncio
async def test_context_is_ready_only_for_fresh_complete_chain() -> None:
    clinic_id, patient_id, rows, review = _chain()
    context = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).build_context(clinic_id=clinic_id, patient_id=patient_id)

    assert context.ready_for_advice is True
    assert context.missing_or_stale == []
    assert [stage.stage for stage in context.stages] == list(StageName)
    assert all(stage.state is StageState.READY for stage in context.stages)
    assert context.canonical_record_mutation is False


@pytest.mark.asyncio
async def test_missing_second_review_fails_closed_and_stays_explicit() -> None:
    clinic_id, patient_id, rows, _ = _chain(second_review=False)
    service = ClinicalCopilotService(FakeDB(rows))
    context = await service.build_context(clinic_id=clinic_id, patient_id=patient_id)

    second_review = context.stages[-1]
    assert second_review.stage is StageName.AI_SECOND_REVIEW
    assert second_review.state is StageState.UNAVAILABLE
    assert second_review.reason == "ai_second_review_contract_unavailable"
    assert context.ready_for_advice is False


@pytest.mark.asyncio
async def test_stale_upstream_provenance_blocks_advice() -> None:
    clinic_id, patient_id, rows, review = _chain(stale_risk=True)
    service = ClinicalCopilotService(FakeDB(rows), second_review_reader=ReviewReader(review))
    context = await service.build_context(clinic_id=clinic_id, patient_id=patient_id)

    risk = next(stage for stage in context.stages if stage.stage is StageName.RISK_ENGINE)
    assert risk.state is StageState.STALE
    assert context.ready_for_advice is False

    clinic_id, patient_id, rows, review = _chain(stale_risk=True)
    service = ClinicalCopilotService(FakeDB(rows), second_review_reader=ReviewReader(review))
    with pytest.raises(ClinicalContextInsufficient):
        await service.advise(
            clinic_id=clinic_id,
            patient_id=patient_id,
            question="What should I review?",
            provider=FakeProvider({"claims": [], "limitations": []}),
            provider_name="fake",
            model="fake-model",
        )


@pytest.mark.asyncio
async def test_advice_is_grounded_redacted_and_tool_free() -> None:
    clinic_id, patient_id, rows, review = _chain()
    provider = FakeProvider(
        {"claims": [{"text": "Review the simulated option.", "evidence_ids": ["SIM-1"]}], "limitations": []}
    )
    result = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).advise(
        clinic_id=clinic_id,
        patient_id=patient_id,
        question="What should I review?",
        provider=provider,
        provider_name="fake",
        model="fake-model",
    )

    assert result.dentist_review_required is True
    assert result.autonomous_diagnosis is False
    assert result.autonomous_treatment_decision is False
    assert result.canonical_record_mutation is False
    assert "Must not leave Dentora" not in provider.last_user_text
    assert "private note" not in provider.last_user_text

    assert _redact_structured({"name": "PHI", "notes": "free", "risk": "high"}) == {"risk": "high"}


@pytest.mark.asyncio
async def test_provider_tool_use_and_unknown_evidence_are_rejected() -> None:
    clinic_id, patient_id, rows, review = _chain()
    service = ClinicalCopilotService(FakeDB(rows), second_review_reader=ReviewReader(review))
    with pytest.raises(ClinicalCopilotOutputError, match="tool_use_forbidden"):
        await service.advise(
            clinic_id=clinic_id,
            patient_id=patient_id,
            question="Review this",
            provider=FakeProvider({}, tool_use=True),
            provider_name="fake",
            model="fake-model",
        )

    clinic_id, patient_id, rows, review = _chain()
    service = ClinicalCopilotService(FakeDB(rows), second_review_reader=ReviewReader(review))
    with pytest.raises(ClinicalCopilotOutputError, match="unsupported_evidence_reference"):
        await service.advise(
            clinic_id=clinic_id,
            patient_id=patient_id,
            question="Review this",
            provider=FakeProvider(
                {"claims": [{"text": "Unsupported", "evidence_ids": ["MADE-UP"]}], "limitations": []}
            ),
            provider_name="fake",
            model="fake-model",
        )
