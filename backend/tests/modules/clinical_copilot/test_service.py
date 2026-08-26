from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.llm.base import Done, TextDelta, ToolUse
from app.modules.case_intelligence.aggregation import SECTION_ORDER
from app.modules.case_intelligence.contracts import CASE_SNAPSHOT_CONTRACT_VERSION
from app.modules.clinical_copilot.contracts import StageName, StageState
from app.modules.clinical_copilot.ports import SecondReviewArtifact
from app.modules.clinical_copilot.service import (
    ClinicalContextInsufficientError,
    ClinicalCopilotOutputError,
    ClinicalCopilotService,
    _redact_structured,
)
from app.modules.risk_engine.contracts import RISK_ENGINE_VERSION, RISK_POLICY_VERSION


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
        self.tools = None
        self.called = False

    def complete(self, *, system, messages, tools, model, max_tokens):
        self.called = True
        self.last_user_text = messages[0].content[0].text
        self.tools = tools

        async def stream():
            if self.tool_use:
                yield ToolUse(id="call-1", name="write_record", input={})
                return
            yield TextDelta(text=json.dumps(self.payload))
            yield Done(stop_reason="stop")

        return stream()


def _chain(
    *,
    second_review=True,
    stale_risk=False,
    incomplete_case=False,
    risk_availability="available",
    planning_review_status="accepted",
    second_review_review_status="accepted",
):
    clinic_id = uuid4()
    patient_id = uuid4()
    reviewer_id = uuid4()
    now = datetime.now(UTC)
    snapshot_id = uuid4()
    planning_id = uuid4()
    simulation_id = uuid4()
    internal_trace_uuid = uuid4()
    source_digest = "sha256:" + "1" * 64
    risk_input = "sha256:" + "2" * 64
    risk_output = "sha256:" + "3" * 64
    planning_output = "sha256:" + "4" * 64
    simulation_output = "sha256:" + "5" * 64
    availability = {name: "available" for name in SECTION_ORDER}
    missing_data_report = []
    if incomplete_case:
        availability["media"] = "not_available"
        missing_data_report = ["media"]

    snapshot = SimpleNamespace(
        id=snapshot_id,
        snapshot_version=4,
        contract_version=CASE_SNAPSHOT_CONTRACT_VERSION,
        generated_at=now,
        source_digest=source_digest,
        snapshot_data={
            "availability": availability,
            "missing_data_report": missing_data_report,
            "provenance": [{"source_record_id": "CASE-1", "evidence_id": "CASE-E1"}],
            "patient": {
                "id": str(patient_id),
                "name": "Must not leave Dentora",
                "notes": "private note",
            },
        },
    )
    risk = SimpleNamespace(
        id=uuid4(),
        result_version=2,
        generated_at=now,
        case_snapshot_version=4,
        case_snapshot_contract_version=CASE_SNAPSHOT_CONTRACT_VERSION,
        source_digest=("sha256:" + "9" * 64) if stale_risk else source_digest,
        input_digest=risk_input,
        result_digest=risk_output,
        engine_version=RISK_ENGINE_VERSION,
        policy_version=RISK_POLICY_VERSION,
        availability_state=risk_availability,
        review_status="pending_review",
        result_data={"evidence": [{"evidence_id": "RISK-1"}], "notes": "drop me"},
    )
    planning = SimpleNamespace(
        id=planning_id,
        planning_version=3,
        generated_at=now,
        case_snapshot_version=4,
        case_snapshot_contract_version=CASE_SNAPSHOT_CONTRACT_VERSION,
        case_source_digest=source_digest,
        risk_engine_version=RISK_ENGINE_VERSION,
        risk_policy_version=RISK_POLICY_VERSION,
        risk_input_digest=risk_input,
        risk_result_digest=risk_output,
        output_digest=planning_output,
        review_status=planning_review_status,
        reviewed_at=now if planning_review_status == "accepted" else None,
        reviewed_by=reviewer_id if planning_review_status == "accepted" else None,
        planning_data={"options": [{"option_id": "OPTION-1", "evidence_ids": ["RISK-1"]}]},
    )
    simulation = SimpleNamespace(
        id=simulation_id,
        simulation_version=1,
        generated_at=now,
        case_snapshot_version=4,
        case_snapshot_contract_version=CASE_SNAPSHOT_CONTRACT_VERSION,
        case_source_digest=source_digest,
        risk_engine_version=RISK_ENGINE_VERSION,
        risk_policy_version=RISK_POLICY_VERSION,
        risk_input_digest=risk_input,
        risk_result_digest=risk_output,
        planning_id=planning_id,
        planning_version=3,
        planning_output_digest=planning_output,
        planning_reviewed_at=planning.reviewed_at,
        planning_reviewed_by=planning.reviewed_by,
        output_digest=simulation_output,
        option_id="OPTION-1",
        scene_data={
            "evidence_ids": ["SIM-1"],
            "predicted_outcome": False,
            "trace_reference": str(internal_trace_uuid),
        },
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
            review_status=second_review_review_status,
            reviewed_at=now if second_review_review_status == "accepted" else None,
            reviewed_by=reviewer_id if second_review_review_status == "accepted" else None,
            evidence_refs=["REVIEW-1"],
            payload={"status": "reviewed", "evidence_ids": ["REVIEW-1"]},
        )
    return clinic_id, patient_id, [snapshot, risk, planning, simulation], review


def _advice_args(clinic_id, patient_id, provider):
    return {
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "focus": "case_review",
        "provider": provider,
        "provider_name": "fake",
        "model": "fake-model",
        "user_id": uuid4(),
        "user_role": "dentist",
    }


@pytest.mark.asyncio
async def test_context_is_ready_only_for_fresh_complete_reviewed_chain() -> None:
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
async def test_incomplete_case_intelligence_fails_closed() -> None:
    clinic_id, patient_id, rows, review = _chain(incomplete_case=True)
    context = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).build_context(clinic_id=clinic_id, patient_id=patient_id)

    case = next(stage for stage in context.stages if stage.stage is StageName.CASE_INTELLIGENCE)
    assert case.state is StageState.MISSING
    assert case.reason == "case_snapshot_contains_missing_sources"
    assert context.ready_for_advice is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("availability", "expected_state"),
    [("unavailable", StageState.UNAVAILABLE), ("invalid_or_stale", StageState.STALE)],
)
async def test_unusable_risk_context_fails_closed(availability, expected_state) -> None:
    clinic_id, patient_id, rows, review = _chain(risk_availability=availability)
    context = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).build_context(clinic_id=clinic_id, patient_id=patient_id)

    risk = next(stage for stage in context.stages if stage.stage is StageName.RISK_ENGINE)
    assert risk.state is expected_state
    assert context.ready_for_advice is False


@pytest.mark.asyncio
async def test_unreviewed_treatment_planning_fails_closed() -> None:
    clinic_id, patient_id, rows, review = _chain(planning_review_status="pending_review")
    context = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).build_context(clinic_id=clinic_id, patient_id=patient_id)

    planning = next(
        stage for stage in context.stages if stage.stage is StageName.TREATMENT_PLANNING
    )
    assert planning.state is StageState.STALE
    assert planning.reason == "treatment_planning_not_accepted_or_reviewed"
    assert context.ready_for_advice is False


@pytest.mark.asyncio
async def test_accepted_planning_requires_complete_reviewer_provenance() -> None:
    clinic_id, patient_id, rows, review = _chain()
    rows[2].reviewed_by = None
    rows[3].planning_reviewed_by = None

    context = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).build_context(clinic_id=clinic_id, patient_id=patient_id)

    planning = next(
        stage for stage in context.stages if stage.stage is StageName.TREATMENT_PLANNING
    )
    assert planning.state is StageState.STALE
    assert planning.reason == "treatment_planning_not_accepted_or_reviewed"
    assert context.ready_for_advice is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["version", "reviewer"])
async def test_simulation_requires_matching_planning_review_provenance(mismatch) -> None:
    clinic_id, patient_id, rows, review = _chain()
    simulation = rows[3]
    if mismatch == "version":
        simulation.planning_version += 1
    else:
        simulation.planning_reviewed_by = uuid4()

    context = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).build_context(clinic_id=clinic_id, patient_id=patient_id)

    stage = next(item for item in context.stages if item.stage is StageName.TREATMENT_SIMULATION)
    assert stage.state is StageState.STALE
    assert stage.reason == "treatment_simulation_provenance_is_stale"
    assert context.ready_for_advice is False


@pytest.mark.asyncio
async def test_unreviewed_second_review_fails_closed() -> None:
    clinic_id, patient_id, rows, review = _chain(second_review_review_status="pending_review")
    context = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).build_context(clinic_id=clinic_id, patient_id=patient_id)

    second_review = context.stages[-1]
    assert second_review.state is StageState.STALE
    assert second_review.reason == "ai_second_review_not_accepted_or_reviewed"
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
    with pytest.raises(ClinicalContextInsufficientError):
        await service.advise(
            **_advice_args(
                clinic_id,
                patient_id,
                FakeProvider({"claims": [], "limitations": []}),
            )
        )


@pytest.mark.asyncio
async def test_advice_is_grounded_redacted_tool_free_and_provenanced() -> None:
    clinic_id, patient_id, rows, review = _chain()
    internal_trace_uuid = rows[3].scene_data["trace_reference"]
    provider = FakeProvider(
        {
            "claims": [{"text": "Review the simulated option.", "evidence_ids": ["SIM-1"]}],
            "limitations": [],
        }
    )
    args = _advice_args(clinic_id, patient_id, provider)
    result = await ClinicalCopilotService(
        FakeDB(rows), second_review_reader=ReviewReader(review)
    ).advise(**args)

    assert result.dentist_review_required is True
    assert result.autonomous_diagnosis is False
    assert result.autonomous_treatment_decision is False
    assert result.canonical_record_mutation is False
    assert provider.tools == []
    assert "Must not leave Dentora" not in provider.last_user_text
    assert "private note" not in provider.last_user_text
    assert "CASE-1" not in provider.last_user_text
    assert str(patient_id) not in provider.last_user_text
    assert str(clinic_id) not in provider.last_user_text
    assert internal_trace_uuid not in provider.last_user_text
    assert "REF_" in provider.last_user_text
    assert result.provenance.generated_by == args["user_id"]
    assert result.provenance.output_digest.startswith("sha256:")
    assert [stage.stage for stage in result.provenance.upstream] == list(StageName)

    assert _redact_structured(
        {
            "name": "PHI",
            "notes": "free",
            "source_record_id": "CASE-1",
            "risk": "high",
            "evidence_id": "E001",
        }
    ) == {"risk": "high", "evidence_id": "E001"}


def test_internal_uuid_values_are_opaque_even_under_safe_or_neutral_keys() -> None:
    evidence_uuid = str(uuid4())
    neutral_uuid = str(uuid4())
    redacted = _redact_structured(
        {
            "evidence_id": evidence_uuid,
            "trace_reference": neutral_uuid,
        }
    )

    serialized = json.dumps(redacted)
    assert evidence_uuid not in serialized
    assert neutral_uuid not in serialized
    assert redacted["evidence_id"].startswith("REF_")
    assert redacted["trace_reference"].startswith("REF_")


@pytest.mark.asyncio
async def test_non_dentist_service_use_is_rejected_before_provider_call() -> None:
    clinic_id, patient_id, rows, review = _chain()
    provider = FakeProvider(
        {"claims": [{"text": "No", "evidence_ids": ["SIM-1"]}], "limitations": []}
    )
    args = _advice_args(clinic_id, patient_id, provider)
    args["user_role"] = "admin"

    with pytest.raises(PermissionError, match="dentist_control_required"):
        await ClinicalCopilotService(
            FakeDB(rows), second_review_reader=ReviewReader(review)
        ).advise(**args)
    assert provider.called is False


@pytest.mark.asyncio
async def test_provider_tool_use_and_unknown_evidence_are_rejected() -> None:
    clinic_id, patient_id, rows, review = _chain()
    service = ClinicalCopilotService(FakeDB(rows), second_review_reader=ReviewReader(review))
    with pytest.raises(ClinicalCopilotOutputError, match="tool_use_forbidden"):
        await service.advise(**_advice_args(clinic_id, patient_id, FakeProvider({}, tool_use=True)))

    clinic_id, patient_id, rows, review = _chain()
    service = ClinicalCopilotService(FakeDB(rows), second_review_reader=ReviewReader(review))
    with pytest.raises(ClinicalCopilotOutputError, match="unsupported_evidence_reference"):
        await service.advise(
            **_advice_args(
                clinic_id,
                patient_id,
                FakeProvider(
                    {
                        "claims": [{"text": "Unsupported", "evidence_ids": ["MADE-UP"]}],
                        "limitations": [],
                    }
                ),
            )
        )
