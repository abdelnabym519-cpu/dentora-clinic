import json

import pytest

from app.core.llm.base import Done, TextDelta
from app.modules.ai_treatment_planning.generator import (
    PlanningGenerationError,
    generate_planning_options,
)


class StaticProvider:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, **_kwargs):
        yield TextDelta(json.dumps(self.payload))
        yield Done("stop")


def _input():
    return {
        "case": {
            "evidence": {"E001": {"source_module": "odontogram"}},
            "sections": {
                "odontogram": {
                    "status": "available",
                    "reason": None,
                    "data": {},
                    "evidence_ids": ["E001"],
                },
                "nerve": {
                    "status": "not_available",
                    "reason": "nerve_analysis_not_available",
                    "data": {},
                    "evidence_ids": [],
                },
            },
        },
        "risk_context": {
            "factors": [
                {
                    "factor_id": "accepted_nerve_pathway_present",
                    "state": "not_available",
                }
            ]
        },
    }


def _valid_output():
    return {
        "options": [
            {
                "option_id": "O1",
                "title": "Staged review option",
                "clinical_intent": "Address the documented finding conservatively.",
                "rationale": "This option is grounded in the available structured finding.",
                "evidence_ids": ["E001"],
                "risk_factor_ids": ["accepted_nerve_pathway_present"],
                "steps": [
                    {
                        "step_id": "S1",
                        "description": "Review the documented finding before selecting treatment.",
                        "purpose": "Keep the treatment decision tied to current evidence.",
                        "evidence_ids": ["E001"],
                        "risk_factor_ids": ["accepted_nerve_pathway_present"],
                    }
                ],
                "uncertainties": ["Nerve data is not available."],
                "alternatives_or_tradeoffs": [
                    "Defer treatment choice until missing data is reviewed."
                ],
            }
        ],
        "data_gaps": [{"section": "nerve", "status": "not_available"}],
    }


@pytest.mark.asyncio
async def test_generator_validates_traceability_and_server_stamps_gap_reason():
    result = await generate_planning_options(
        provider=StaticProvider(_valid_output()),
        model="test-model",
        llm_input=_input(),
        max_tokens=1000,
    )
    assert result.content.options[0].evidence_ids == ["E001"]
    assert result.content.options[0].steps[0].risk_factor_ids == ["accepted_nerve_pathway_present"]
    assert result.content.data_gaps[0].reason == "nerve_analysis_not_available"
    assert result.content.no_automatic_execution is True


@pytest.mark.asyncio
async def test_generator_rejects_unknown_evidence():
    payload = _valid_output()
    payload["options"][0]["steps"][0]["evidence_ids"] = ["E999"]
    with pytest.raises(PlanningGenerationError, match="unknown_evidence"):
        await generate_planning_options(
            provider=StaticProvider(payload),
            model="test-model",
            llm_input=_input(),
            max_tokens=1000,
        )


@pytest.mark.asyncio
async def test_generator_rejects_unknown_risk_factor():
    payload = _valid_output()
    payload["options"][0]["risk_factor_ids"] = ["invented_risk"]
    with pytest.raises(PlanningGenerationError, match="unknown_risk_factor"):
        await generate_planning_options(
            provider=StaticProvider(payload),
            model="test-model",
            llm_input=_input(),
            max_tokens=1000,
        )


@pytest.mark.asyncio
async def test_generator_rejects_omitted_data_gap():
    payload = _valid_output()
    payload["data_gaps"] = []
    with pytest.raises(PlanningGenerationError, match="omitted_or_invented_data_gap"):
        await generate_planning_options(
            provider=StaticProvider(payload),
            model="test-model",
            llm_input=_input(),
            max_tokens=1000,
        )
