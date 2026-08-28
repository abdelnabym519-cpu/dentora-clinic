"""AI Treatment Planning contract and generator tests."""

from __future__ import annotations

import json

import pytest

from app.core.llm.base import Done, TextDelta
from app.modules.ai_case_summary.treatment_contracts import AITreatmentPlan
from app.modules.ai_case_summary.treatment_generator import (
    TreatmentGenerationError,
    generate_treatment_plan,
)


class _Provider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def complete(self, **_kwargs):
        yield TextDelta(json.dumps(self.payload))
        yield Done("stop")


def _input() -> dict:
    return {
        "evidence": {"E001": {"source_module": "odontogram"}},
        "sections": {
            "odontogram": {
                "status": "available",
                "data": {"finding_count": 1},
                "evidence_ids": ["E001"],
                "reason": None,
            },
            "periodontogram": {
                "status": "not_available",
                "data": {},
                "evidence_ids": [],
                "reason": "not_recorded",
            },
        },
    }


@pytest.mark.asyncio
async def test_generator_accepts_grounded_options_and_preserves_data_gaps() -> None:
    provider = _Provider(
        {
            "options": [
                {
                    "option_id": "O1",
                    "title": "Conservative staged option",
                    "intent": "Address the observed finding after clinician verification.",
                    "steps": [
                        {
                            "step_id": "S1",
                            "action": "Clinician verifies the observed finding before intervention.",
                            "rationale": "The proposal is grounded only in the available odontogram evidence.",
                            "evidence_ids": ["E001"],
                            "prerequisites": ["Complete dentist examination"],
                        }
                    ],
                }
            ],
            "data_gaps": [
                {
                    "section": "periodontogram",
                    "status": "not_available",
                    "reason": "ignored-by-server",
                }
            ],
            "limitations": ["No periodontal data were available."],
        }
    )

    result = await generate_treatment_plan(
        provider=provider,
        model="test-model",
        llm_input=_input(),
        max_tokens=500,
    )

    assert result.content.options[0].steps[0].evidence_ids == ["E001"]
    assert result.content.data_gaps[0].reason == "not_recorded"
    assert result.content.advisory_only is True


@pytest.mark.asyncio
async def test_generator_rejects_unknown_evidence() -> None:
    provider = _Provider(
        {
            "options": [
                {
                    "option_id": "O1",
                    "title": "Invalid option",
                    "intent": "Invalid",
                    "steps": [
                        {
                            "step_id": "S1",
                            "action": "Do something unsupported.",
                            "rationale": "Unsupported.",
                            "evidence_ids": ["E999"],
                            "prerequisites": [],
                        }
                    ],
                }
            ],
            "data_gaps": [{"section": "periodontogram", "status": "not_available", "reason": None}],
            "limitations": [],
        }
    )

    with pytest.raises(TreatmentGenerationError, match="unknown_evidence"):
        await generate_treatment_plan(
            provider=provider,
            model="test-model",
            llm_input=_input(),
            max_tokens=500,
        )


@pytest.mark.asyncio
async def test_generator_rejects_omitted_required_data_gap() -> None:
    provider = _Provider({"options": [], "data_gaps": [], "limitations": []})

    with pytest.raises(TreatmentGenerationError, match="omitted_or_invented_data_gap"):
        await generate_treatment_plan(
            provider=provider,
            model="test-model",
            llm_input=_input(),
            max_tokens=500,
        )


def test_contract_cannot_claim_canonical_plan_application() -> None:
    with pytest.raises(Exception):
        AITreatmentPlan.model_validate(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "patient_id": "00000000-0000-0000-0000-000000000002",
                "plan_version": 1,
                "inputs": {
                    "case_snapshot_version": 1,
                    "case_snapshot_contract_version": "1.0",
                    "case_source_digest": "sha256:" + "a" * 64,
                    "summary_id": "00000000-0000-0000-0000-000000000003",
                    "summary_version": 1,
                    "summary_output_digest": "sha256:" + "b" * 64,
                    "risk_result_id": "00000000-0000-0000-0000-000000000004",
                    "risk_result_version": 1,
                    "risk_result_digest": "sha256:" + "c" * 64,
                },
                "content": {"options": [], "data_gaps": [], "limitations": []},
                "provenance": {
                    "provider": "test",
                    "model": "test",
                    "provider_contract_version": "1",
                    "prompt_version": "1",
                    "input_digest": "sha256:" + "d" * 64,
                    "output_digest": "sha256:" + "e" * 64,
                },
                "review_status": "pending_review",
                "clinical_output": False,
                "generated_at": "2026-08-26T00:00:00Z",
                "applied_to_treatment_plan": True,
            }
        )
