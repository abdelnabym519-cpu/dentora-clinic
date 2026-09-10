"""Regression: provider misconfiguration surfaces as explicit 503 states.

The activation mission requires that an unconfigured/unreachable LLM
provider produces an actionable, distinct failure state — never a generic
500 and never a misleading "failed validation" (LLMConfigError used to be
swallowed by the broader ``LLMError`` handlers). These tests pin the
``503 + <module>_provider_unavailable`` mapping for the AI generation
surfaces, mirroring the pattern that already existed in
``clinical_copilot`` and ``ai_clinical_report``.
"""

import pytest

from app.core.llm.base import LLMConfigError

CONFIG_ERROR_MESSAGE = (
    "OpenAI provider selected but OPENAI_API_KEY is not configured"
)


def _raising_factory(_name: str):
    raise LLMConfigError(CONFIG_ERROR_MESSAGE)


@pytest.mark.asyncio
async def test_case_summary_provider_unavailable(
    client, auth_headers, test_patient, monkeypatch
) -> None:
    from app.modules.ai_case_summary.service import AICaseSummaryService

    monkeypatch.setattr(
        AICaseSummaryService, "provider_factory", staticmethod(_raising_factory)
    )
    response = await client.post(
        f"/api/v1/ai_case_summary/patients/{test_patient.id}", headers=auth_headers
    )
    assert response.status_code == 503
    body = response.json()
    assert body["data"] is None
    assert "ai_case_summary_provider_unavailable" in body["message"]
    assert CONFIG_ERROR_MESSAGE in body["message"]


@pytest.mark.asyncio
async def test_treatment_plan_draft_provider_unavailable(
    client, auth_headers, test_patient, monkeypatch
) -> None:
    """The draft router maps provider misconfiguration to 503 even though
    the service resolves the upstream case state first."""
    from app.modules.ai_case_summary.treatment_service import (
        AITreatmentPlanningService,
    )

    async def _raise(*args, **kwargs):
        raise LLMConfigError(CONFIG_ERROR_MESSAGE)

    monkeypatch.setattr(AITreatmentPlanningService, "generate", _raise)
    response = await client.post(
        f"/api/v1/ai_case_summary/patients/{test_patient.id}/treatment-planning",
        headers=auth_headers,
    )
    assert response.status_code == 503
    body = response.json()
    assert body["data"] is None
    assert "ai_case_summary_provider_unavailable" in body["message"]


@pytest.mark.asyncio
async def test_treatment_planning_provider_unavailable(
    client, auth_headers, test_patient, monkeypatch
) -> None:
    from app.modules.ai_treatment_planning.service import AITreatmentPlanningService

    monkeypatch.setattr(
        AITreatmentPlanningService, "provider_factory", staticmethod(_raising_factory)
    )
    response = await client.post(
        f"/api/v1/ai_treatment_planning/patients/{test_patient.id}", headers=auth_headers
    )
    assert response.status_code == 503
    body = response.json()
    assert body["data"] is None
    assert "ai_treatment_planning_provider_unavailable" in body["message"]


@pytest.mark.asyncio
async def test_second_review_provider_unavailable(
    client, auth_headers, test_patient, monkeypatch
) -> None:
    """The second-review router maps provider misconfiguration to 503 even
    though the service resolves the simulation chain first."""
    from app.modules.ai_second_review.service import AISecondReviewService
    from uuid import uuid4

    async def _raise(*args, **kwargs):
        raise LLMConfigError(CONFIG_ERROR_MESSAGE)

    monkeypatch.setattr(AISecondReviewService, "generate", _raise)
    response = await client.post(
        f"/api/v1/ai_second_review/patients/{test_patient.id}",
        headers=auth_headers,
        json={"simulation_id": str(uuid4())},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["data"] is None
    assert "ai_second_review_provider_unavailable" in body["message"]
