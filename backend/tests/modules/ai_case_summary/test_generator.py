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
        "evidence": {"E001": {"source_module": "odontogram"}},
        "sections": {
            "odontogram": {"status": "available", "data": {"tooth": 16}},
            "nerve": {
                "status": "invalid_or_stale",
                "data": None,
                "reason": "nerve_analysis_not_accepted",
            },
        },
    }


@pytest.mark.asyncio
async def test_generator_requires_traceable_claims_and_complete_gaps() -> None:
    provider = FakeProvider(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "text": "Tooth 16 is present.",
                    "evidence_ids": ["E001"],
                }
            ],
            "data_gaps": [{"section": "nerve", "status": "invalid_or_stale"}],
        }
    )
    result = await generate_summary(
        provider=provider, model="test-model", llm_input=_input(), max_tokens=1000
    )
    assert result.content.advisory_only is True
    assert result.content.claims[0].evidence_ids == ["E001"]
    assert result.content.data_gaps[0].reason == "nerve_analysis_not_accepted"
    assert provider.calls[0]["tools"] == []


@pytest.mark.asyncio
async def test_generator_rejects_unknown_evidence() -> None:
    provider = FakeProvider(
        {
            "claims": [{"claim_id": "C1", "text": "Invented.", "evidence_ids": ["E999"]}],
            "data_gaps": [{"section": "nerve", "status": "invalid_or_stale"}],
        }
    )
    with pytest.raises(SummaryGenerationError, match="unknown_evidence"):
        await generate_summary(provider=provider, model="test", llm_input=_input(), max_tokens=100)


@pytest.mark.asyncio
async def test_generator_rejects_omitted_missing_or_stale_data() -> None:
    provider = FakeProvider(
        {
            "claims": [{"claim_id": "C1", "text": "Fact.", "evidence_ids": ["E001"]}],
            "data_gaps": [],
        }
    )
    with pytest.raises(SummaryGenerationError, match="omitted_or_invented_data_gap"):
        await generate_summary(provider=provider, model="test", llm_input=_input(), max_tokens=100)
