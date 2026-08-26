from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.llm.base import Done, TextDelta
from app.modules.ai_treatment_planning.contracts import ReviewStatus
from app.modules.copilot.clinical_contracts import ClinicalCopilotRequest
from app.modules.copilot.clinical_generator import (
    ClinicalCopilotGenerationError,
    generate_clinical_copilot,
)
from app.modules.copilot.clinical_service import ClinicalCopilotService, ClinicalCopilotUnavailable
from app.modules.risk_engine.contracts import RISK_ENGINE_VERSION, RISK_POLICY_VERSION


class FakeProvider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        yield TextDelta(json.dumps(self.payload))
        yield Done("stop")


def _llm_input() -> dict:
    return {
        "case": {"evidence": {"E001": {}}, "sections": {}},
        "risk_context": {"factors": [{"factor_id": "risk-a"}]},
        "reviewed_planning": {"options": [{"option_id": "opt-a"}]},
        "reviewed_simulation": {"checkpoints": [{"checkpoint_id": "baseline"}]},
        "required_limitations": [
            {"section": "periodontogram", "status": "not_available", "reason": "not installed"}
        ],
    }


@pytest.mark.asyncio
async def test_generator_accepts_only_traceable_structured_claims():
    provider = FakeProvider(
        {
            "summary": "Review the accepted evidence with the dentist.",
            "claims": [
                {
                    "claim_id": "C001",
                    "text": "The reviewed workflow contains the selected option.",
                    "evidence_ids": ["E001"],
                    "risk_factor_ids": ["risk-a"],
                    "planning_option_ids": ["opt-a"],
                    "simulation_checkpoint_ids": ["baseline"],
                }
            ],
            "limitations": [
                {
                    "section": "periodontogram",
                    "status": "not_available",
                    "reason": "model cannot override source reason",
                }
            ],
            "questions_for_dentist": ["Is additional evidence needed before deciding?"],
        }
    )

    result = await generate_clinical_copilot(
        provider=provider,
        model="fake",
        llm_input=_llm_input(),
        max_tokens=500,
    )

    assert result.content.advisory_only is True
    assert result.content.autonomous_diagnosis is False
    assert result.content.autonomous_treatment_decision is False
    assert result.content.canonical_record_mutation is False
    assert result.content.claims[0].evidence_ids == ["E001"]
    assert result.content.limitations[0].reason == "not installed"
    assert provider.calls[0]["tools"] == []


@pytest.mark.asyncio
async def test_generator_rejects_unknown_evidence_reference():
    provider = FakeProvider(
        {
            "summary": "Unsupported claim.",
            "claims": [
                {
                    "claim_id": "C001",
                    "text": "Unsupported.",
                    "evidence_ids": ["E999"],
                    "risk_factor_ids": [],
                    "planning_option_ids": [],
                    "simulation_checkpoint_ids": [],
                }
            ],
            "limitations": [
                {"section": "periodontogram", "status": "not_available", "reason": None}
            ],
            "questions_for_dentist": [],
        }
    )

    with pytest.raises(
        ClinicalCopilotGenerationError,
        match="clinical_copilot_references_unknown_evidence",
    ):
        await generate_clinical_copilot(
            provider=provider,
            model="fake",
            llm_input=_llm_input(),
            max_tokens=500,
        )


@pytest.mark.asyncio
async def test_generator_rejects_omitted_missing_data():
    provider = FakeProvider(
        {
            "summary": "Incomplete.",
            "claims": [],
            "limitations": [],
            "questions_for_dentist": [],
        }
    )

    with pytest.raises(
        ClinicalCopilotGenerationError,
        match="clinical_copilot_omitted_required_limitation",
    ):
        await generate_clinical_copilot(
            provider=provider,
            model="fake",
            llm_input=_llm_input(),
            max_tokens=500,
        )


def test_request_has_no_arbitrary_free_text_field():
    with pytest.raises(ValidationError):
        ClinicalCopilotRequest.model_validate(
            {"focus": "case_review", "question": "patient free text must not reach cloud"}
        )


def _workflow(*, stale_section: bool = False):
    now = datetime.now(UTC)
    reviewer = uuid4()
    planning_id = uuid4()
    output_digest = "sha256:plan"
    snapshot = SimpleNamespace(
        case_snapshot_version=3,
        contract_version="1.0",
        source_digest="sha256:case",
        availability={
            "clinical": SimpleNamespace(value="invalid_or_stale" if stale_section else "available")
        },
    )
    risk = SimpleNamespace(input_digest="sha256:risk-in", result_digest="sha256:risk-out")
    case_ref = SimpleNamespace(
        case_snapshot_version=3,
        case_snapshot_contract_version="1.0",
        case_source_digest="sha256:case",
        risk_engine_version=RISK_ENGINE_VERSION,
        risk_policy_version=RISK_POLICY_VERSION,
        risk_input_digest="sha256:risk-in",
        risk_result_digest="sha256:risk-out",
    )
    planning = SimpleNamespace(
        id=planning_id,
        planning_version=2,
        review_status=ReviewStatus.ACCEPTED,
        clinical_output=True,
        reviewed_at=now,
        reviewed_by=reviewer,
        case_reference=case_ref,
        provenance=SimpleNamespace(output_digest=output_digest),
    )
    sim_prov = SimpleNamespace(
        planning_id=planning_id,
        planning_version=2,
        planning_output_digest=output_digest,
        planning_reviewed_at=now,
        planning_reviewed_by=reviewer,
        case_snapshot_version=3,
        case_snapshot_contract_version="1.0",
        case_source_digest="sha256:case",
        risk_engine_version=RISK_ENGINE_VERSION,
        risk_policy_version=RISK_POLICY_VERSION,
        risk_input_digest="sha256:risk-in",
        risk_result_digest="sha256:risk-out",
        input_digest="sha256:sim-in",
        output_digest="sha256:sim-out",
    )
    simulation = SimpleNamespace(id=uuid4(), simulation_version=1, provenance=sim_prov)
    return snapshot, risk, planning, simulation


def test_second_review_gate_passes_only_coherent_reviewed_workflow():
    snapshot, risk, planning, simulation = _workflow()
    digest = ClinicalCopilotService._second_review_gate(
        snapshot=snapshot,
        risk_evaluation=risk,
        planning=planning,
        simulation=simulation,
    )
    assert digest.startswith("sha256:")


def test_second_review_gate_fails_closed_on_stale_case_data():
    snapshot, risk, planning, simulation = _workflow(stale_section=True)
    with pytest.raises(ClinicalCopilotUnavailable, match="case_contains_invalid_or_stale_data"):
        ClinicalCopilotService._second_review_gate(
            snapshot=snapshot,
            risk_evaluation=risk,
            planning=planning,
            simulation=simulation,
        )
