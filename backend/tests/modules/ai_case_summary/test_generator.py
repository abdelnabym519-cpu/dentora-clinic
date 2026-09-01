import json

import pytest

from app.core.llm.base import Done, TextDelta, Usage
from app.modules.ai_case_summary.generator import SummaryGenerationError, generate_summary


class FakeProvider:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        yield TextDelta(json.dumps(self.payload))
        yield Usage(input_tokens=10, output_tokens=20)
        yield Done("stop")


def _input():
    return {
        "evidence": {
            "E001": {
                "section": "odontogram",
                "facts": {
                    "tooth_number": 16,
                    "general_condition": "present",
                },
            },
            "E049": {
                "section": "patient",
                "facts": {
                    "status": "active",
                    "preferred_language": "es",
                },
            },
        },
        "sections": {
            "odontogram": {
                "status": "available",
                "evidence_ids": ["E001"],
                "reason": None,
            },
            "patient": {
                "status": "available",
                "evidence_ids": ["E049"],
                "reason": None,
            },
            "nerve": {
                "status": "invalid_or_stale",
                "evidence_ids": [],
                "reason": "nerve_analysis_not_accepted",
            },
        },
    }


@pytest.mark.asyncio
async def test_generator_renders_only_selected_grounded_facts_and_derives_gaps() -> None:
    provider = FakeProvider(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "evidence_id": "E001",
                    "fact_paths": ["tooth_number", "general_condition"],
                }
            ]
        }
    )

    result = await generate_summary(
        provider=provider,
        model="test-model",
        llm_input=_input(),
        max_tokens=1000,
    )

    assert result.content.advisory_only is True
    assert result.content.claims[0].evidence_ids == ["E001"]
    assert result.content.claims[0].text == (
        "Odontogram — tooth number: 16; general condition: present."
    )

    assert result.content.data_gaps[0].section == "nerve"
    assert result.content.data_gaps[0].status == "invalid_or_stale"
    assert result.content.data_gaps[0].reason == "nerve_analysis_not_accepted"

    schema = provider.calls[0]["response_schema"]
    assert provider.calls[0]["tools"] == []
    assert schema["type"] == "object"
    assert schema["properties"]["claims"]["maxItems"] == 8

    claim_schema = schema["$defs"]["_GeneratedClaim"]["properties"]
    assert "evidence_id" in claim_schema
    assert "fact_paths" in claim_schema
    assert "text" not in claim_schema
    assert "evidence_ids" not in claim_schema
    assert "data_gaps" not in schema["properties"]


@pytest.mark.asyncio
async def test_generator_rejects_unknown_evidence() -> None:
    provider = FakeProvider(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "evidence_id": "E999",
                    "fact_paths": ["tooth_number"],
                }
            ]
        }
    )

    with pytest.raises(SummaryGenerationError, match="unknown_evidence"):
        await generate_summary(
            provider=provider,
            model="test",
            llm_input=_input(),
            max_tokens=100,
        )


@pytest.mark.asyncio
async def test_generator_rejects_fact_not_present_in_referenced_evidence() -> None:
    # Reproduces the real E049 failure:
    # patient evidence must never be usable to assert an odontogram fact.
    provider = FakeProvider(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "evidence_id": "E049",
                    "fact_paths": ["tooth_number"],
                }
            ]
        }
    )

    with pytest.raises(SummaryGenerationError, match="unknown_fact_path"):
        await generate_summary(
            provider=provider,
            model="test",
            llm_input=_input(),
            max_tokens=100,
        )


@pytest.mark.asyncio
async def test_generator_rejects_non_scalar_fact() -> None:
    llm_input = _input()
    llm_input["evidence"]["E001"]["facts"]["surfaces"] = ["O", "M"]

    provider = FakeProvider(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "evidence_id": "E001",
                    "fact_paths": ["surfaces"],
                }
            ]
        }
    )

    with pytest.raises(SummaryGenerationError, match="not_scalar"):
        await generate_summary(
            provider=provider,
            model="test",
            llm_input=llm_input,
            max_tokens=100,
        )


@pytest.mark.asyncio
async def test_generator_rejects_provider_written_narrative_or_data_gaps() -> None:
    provider = FakeProvider(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "evidence_id": "E049",
                    "fact_paths": ["status"],
                    "text": "All teeth are healthy.",
                }
            ],
            "data_gaps": [],
        }
    )

    with pytest.raises(
        SummaryGenerationError,
        match="provider_returned_invalid_structured_summary",
    ):
        await generate_summary(
            provider=provider,
            model="test",
            llm_input=_input(),
            max_tokens=100,
        )
