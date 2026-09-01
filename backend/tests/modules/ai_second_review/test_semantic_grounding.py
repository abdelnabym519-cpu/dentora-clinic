from __future__ import annotations

import json

import pytest

from app.core.llm.base import Done, TextDelta
from app.modules.ai_second_review.generator import (
    SecondReviewGenerationError,
    generate_second_review,
)


class StaticProvider:
    def __init__(self, payload: dict):
        self.payload = payload

    async def complete(self, **_kwargs):
        yield TextDelta(json.dumps(self.payload))
        yield Done("stop")


def _llm_input() -> dict:
    return {
        "case": {
            "evidence": {"E001": {"source_module": "fixture"}},
            "sections": {
                "patient": {"status": "available", "reason": None},
                "nerve": {"status": "not_available", "reason": "fixture"},
            },
        },
        "risk_context": {"factors": []},
        "planning": {"allowed_refs": ["option:O1"]},
        "simulation": {"allowed_refs": ["step:S1"]},
    }


def _provider_selection() -> dict:
    return {
        "findings": [
            {
                "finding_id": "F001",
                "category": "evidence_traceability",
                "evidence_ids": [],
                "risk_factor_ids": [],
                "planning_refs": ["option:O1"],
                "simulation_refs": ["step:S1"],
            }
        ],
        "data_gaps": [
            {
                "section": "nerve",
                "status": "not_available",
                "reason": "fixture",
            }
        ],
    }


@pytest.mark.asyncio
async def test_public_statement_is_deterministic_not_provider_authored() -> None:
    result = await generate_second_review(
        provider=StaticProvider(_provider_selection()),
        model="fixture",
        llm_input=_llm_input(),
        max_tokens=1000,
    )

    finding = result.content.findings[0]
    assert finding.statement == "Review evidence traceability for the referenced artifacts."
    assert "No evidence IDs" not in finding.statement
    assert finding.planning_refs == ["option:O1"]
    assert finding.simulation_refs == ["step:S1"]


@pytest.mark.asyncio
async def test_provider_free_statement_is_rejected_fail_closed() -> None:
    payload = _provider_selection()
    payload["findings"][0]["statement"] = (
        "No evidence IDs provided for critical sections in simulation checkpoint"
    )

    with pytest.raises(
        SecondReviewGenerationError,
        match="provider_returned_invalid_structured_second_review",
    ):
        await generate_second_review(
            provider=StaticProvider(payload),
            model="fixture",
            llm_input=_llm_input(),
            max_tokens=1000,
        )
