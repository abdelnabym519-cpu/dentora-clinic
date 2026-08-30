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
            "evidence": {
                "E001": {
                    "section": "odontogram",
                    "facts": {
                        "tooth_number": 16,
                        "general_condition": "present",
                    },
                }
            },
            "sections": {
                "odontogram": {
                    "status": "available",
                    "reason": None,
                    "evidence_ids": ["E001"],
                },
                "nerve": {
                    "status": "not_available",
                    "reason": "nerve_analysis_not_available",
                    "evidence_ids": [],
                },
            },
        },
        "risk_context": {
            "factors": [
                {
                    "factor_id": "accepted_nerve_pathway_present",
                    "label": "Accepted nerve pathway present",
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
                "strategy": "review_documented_findings",
                "evidence": [
                    {
                        "evidence_id": "E001",
                        "fact_paths": ["tooth_number", "general_condition"],
                    }
                ],
                "risk_factor_ids": ["accepted_nerve_pathway_present"],
                "steps": [
                    {
                        "step_id": "S1",
                        "strategy": "stage_clinical_decision",
                        "evidence": [
                            {
                                "evidence_id": "E001",
                                "fact_paths": ["tooth_number"],
                            }
                        ],
                        "risk_factor_ids": ["accepted_nerve_pathway_present"],
                    }
                ],
            }
        ]
    }


@pytest.mark.asyncio
async def test_generator_renders_public_text_from_validated_facts_and_derives_gap():
    result = await generate_planning_options(
        provider=StaticProvider(_valid_output()),
        model="test-model",
        llm_input=_input(),
        max_tokens=1000,
    )

    option = result.content.options[0]
    assert option.evidence_ids == ["E001"]
    assert "tooth number: 16" in option.rationale.lower()
    assert "general condition: present" in option.rationale.lower()
    assert option.steps[0].risk_factor_ids == ["accepted_nerve_pathway_present"]
    assert "tooth number: 16" in option.steps[0].description.lower()
    assert result.content.data_gaps[0].section == "nerve"
    assert result.content.data_gaps[0].status == "not_available"
    assert result.content.data_gaps[0].reason == "nerve_analysis_not_available"
    assert result.content.no_automatic_execution is True


@pytest.mark.asyncio
async def test_generator_rejects_unknown_evidence():
    payload = _valid_output()
    payload["options"][0]["evidence"][0]["evidence_id"] = "E999"
    with pytest.raises(PlanningGenerationError, match="unknown_evidence"):
        await generate_planning_options(
            provider=StaticProvider(payload),
            model="test-model",
            llm_input=_input(),
            max_tokens=1000,
        )


@pytest.mark.asyncio
async def test_generator_rejects_unknown_fact_path():
    payload = _valid_output()
    payload["options"][0]["evidence"][0]["fact_paths"] = ["invented.diagnosis"]
    with pytest.raises(PlanningGenerationError, match="unknown_fact_path"):
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
async def test_generator_rejects_provider_free_clinical_prose():
    payload = _valid_output()
    payload["options"][0]["rationale"] = "Invented periodontal disease."
    with pytest.raises(PlanningGenerationError, match="invalid_structured_planning"):
        await generate_planning_options(
            provider=StaticProvider(payload),
            model="test-model",
            llm_input=_input(),
            max_tokens=1000,
        )


@pytest.mark.asyncio
async def test_generator_rejects_provider_supplied_data_gaps():
    payload = _valid_output()
    payload["data_gaps"] = [
        {
            "section": "nerve",
            "status": "unavailable",
            "reason": "provider-controlled gap",
        }
    ]
    with pytest.raises(PlanningGenerationError, match="invalid_structured_planning"):
        await generate_planning_options(
            provider=StaticProvider(payload),
            model="test-model",
            llm_input=_input(),
            max_tokens=1000,
        )
