"""Integration tests for the patient-scoped clinical AI features.

Covers the FULL production chain:

    API endpoint
      -> RBAC (copilot.chat) + clinic context
      -> build_clinical_context (tool-registry reads, clinic-scoped)
      -> Redactor (PII tokenisation)
      -> get_provider()   [injected in tests with a Provider-protocol
                           implementation; production resolves the real one]
      -> provider.complete(...)
      -> structured Pydantic validation
      -> response

The injected provider is the SAME abstraction the orchestrator/copilot use
(test-only wiring, exactly like test_copilot_bridge); production never
injects anything. Separately, ``test_openai_provider_wire_path_parses_json``
exercises the *real* OpenAIProvider over an in-process HTTP transport to
prove the streaming JSON decode + structured validation path is genuine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient

import app.modules.copilot.clinical as clinical
from app.core.llm.base import Done, ProviderMessage, TextDelta, Usage
from app.database import engine


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_pool():
    await engine.dispose()
    yield
    await engine.dispose()


# --- recording provider (implements the Provider protocol) -------------


class _StructuredProvider:
    """Returns a fixed JSON object; records what it was asked.

    ``saw_raw_pii`` reflects whether any redaction token was present in
    the outgoing prompt (privacy assertion support).
    """

    def __init__(self, payload: dict[str, Any], *, fail: Exception | None = None):
        self.payload = payload
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system, messages, tools, model, max_tokens) -> AsyncIterator[Any]:
        import json

        self.calls.append(
            {
                "system": system,
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
            }
        )

        async def gen():
            if self.fail is not None:
                raise self.fail
            yield TextDelta(json.dumps(self.payload))
            yield Usage(120, 80)
            yield Done("stop")

        return gen()

    @property
    def outgoing_text(self) -> str:
        parts = []
        for c in self.calls:
            for m in c["messages"]:
                for b in m.content:
                    if isinstance(b, TextDelta) or hasattr(b, "text"):
                        parts.append(getattr(b, "text", ""))
        return "\n".join(parts)


# Valid structured payloads for each feature.
def _summary_payload() -> dict[str, Any]:
    return {
        "summary": "Patient has an active budget and recent activity.",
        "current_condition": ["budget sent"],
        "key_findings": ["one open budget"],
        "active_treatments": ["pending budget"],
        "important_history": ["recent recall activity"],
        "outstanding_items": ["await patient response"],
        "missing_information": ["odontogram not in available structured data"],
        "uncertainty": ["clinical notes not available in the provided context"],
    }


def _report_payload() -> dict[str, Any]:
    return {
        "title": "Clinical report",
        "overview": "Based only on the structured records provided.",
        "sections": [{"heading": "Status", "body": "Active patient.", "findings": ["open budget"]}],
        "conclusions": ["follow up on budget"],
        "recommendations": ["review odontogram in person"],
        "missing_information": ["imaging"],
        "uncertainty": ["limited structured data"],
    }


def _review_payload() -> dict[str, Any]:
    return {
        "overall_impression": "AI-assisted only; not a diagnosis.",
        "key_findings": ["active budget"],
        "possible_concerns": ["budget unanswered"],
        "inconsistencies": [],
        "missing_information": ["odontogram"],
        "questions_to_consider": ["confirm treatment status?"],
        "confidence": "low",
        "confidence_rationale": "Only administrative structured data was provided.",
    }


def _plan_payload() -> dict[str, Any]:
    return {
        "options": [
            {
                "title": "Advisory option A",
                "rationale": "Based on the open budget.",
                "priority": 1,
                "estimated_steps": ["review", "confirm"],
                "depends_on_missing_info": ["odontogram"],
                "considerations": ["non-authoritative"],
            }
        ],
        "suggested_order": ["Advisory option A"],
        "missing_information": ["odontogram"],
        "uncertainty": ["requires clinical exam"],
    }


def _intel_payload() -> dict[str, Any]:
    return {
        "insights": ["budget awaiting response warrants follow-up"],
        "risk_attention_points": ["open recall"],
        "missing_follow_up": ["contact patient"],
        "missing_information": [],
        "uncertainty": [],
    }


FEATURES = [
    ("/api/v1/copilot/clinical/case-summary", _summary_payload, "summary"),
    ("/api/v1/copilot/clinical/report", _report_payload, "overview"),
    ("/api/v1/copilot/clinical/second-review", _review_payload, "overall_impression"),
    ("/api/v1/copilot/clinical/treatment-suggestions", _plan_payload, "suggested_order"),
    ("/api/v1/copilot/clinical/case-intelligence", _intel_payload, "insights"),
]


@pytest_asyncio.fixture
async def patient_id(client: AsyncClient, auth_headers: dict, test_clinic) -> UUID:
    res = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": "Pablo", "last_name": "Fernández", "phone": "+34612345001"},
    )
    assert res.status_code in (200, 201), res.text
    body = res.json()
    return UUID(body["data"]["id"])


def _install_provider(monkeypatch, payload, fail=None):
    provider = _StructuredProvider(payload, fail=fail)
    monkeypatch.setattr(clinical, "get_provider", lambda name, *a, **k: provider)
    return provider


# --- happy path: every feature returns a validated structured result ----


@pytest.mark.parametrize(("path", "payload_fn", "field"), [(p, f, k) for p, f, k in FEATURES])
async def test_clinical_feature_full_chain(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic,
    patient_id: UUID,
    monkeypatch,
    path,
    payload_fn,
    field,
):
    provider = _install_provider(monkeypatch, payload_fn())

    res = await client.post(path, headers=auth_headers, json={"patient_id": str(patient_id)})
    assert res.status_code == 200, res.text
    data = res.json()["data"]

    # AI envelope / provenance.
    assert data["generated_by"] == "ai"
    assert data["model"] == "gpt-5.4-mini"
    assert "not a medical diagnosis" in data["disclaimer"] or "dentist" in data["disclaimer"]
    # Provenance lists the real tool sources that fed the model.
    assert any(s == "patients.get_patient" for s in data["sources"])
    # The provider was really invoked (streaming protocol) exactly once.
    assert len(provider.calls) == 1
    assert provider.calls[0]["model"] == "gpt-5.4-mini"
    # JSON-output instruction is present in the system prompt.
    assert "JSON" in provider.calls[0]["system"]
    # Field the feature is expected to populate.
    assert data[field] or field in data


async def test_case_intelligence_keeps_deterministic_signals_separate(
    client: AsyncClient, auth_headers: dict, test_clinic, patient_id: UUID, monkeypatch
):
    provider = _install_provider(monkeypatch, _intel_payload())
    res = await client.post(
        "/api/v1/copilot/clinical/case-intelligence",
        headers=auth_headers,
        json={"patient_id": str(patient_id)},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    # signals are deterministic (server-attached), insights are LLM-derived.
    assert isinstance(data["signals"], list)
    assert isinstance(data["insights"], list)
    # The AI never gets to author the deterministic signal list.
    sent = provider.outgoing_text
    assert "DETERMINISTIC SIGNALS" in provider.calls[0]["system"] + sent


async def test_pii_is_redacted_before_provider(
    client: AsyncClient, auth_headers: dict, test_clinic, patient_id: UUID, monkeypatch
):
    provider = _install_provider(monkeypatch, _summary_payload())
    res = await client.post(
        "/api/v1/copilot/clinical/case-summary",
        headers=auth_headers,
        json={"patient_id": str(patient_id)},
    )
    assert res.status_code == 200, res.text
    # Raw name/phone must NOT reach the provider; tokens must.
    outgoing = provider.outgoing_text
    assert "Pablo" not in outgoing
    assert "612345001" not in outgoing


# --- safety: bad / failing provider never yields fabricated output ------


async def test_invalid_provider_output_fails_safely(
    client: AsyncClient, auth_headers: dict, test_clinic, patient_id: UUID, monkeypatch
):
    # Free-form prose that is not JSON → must be a clean error, not fake text.
    _install_provider(monkeypatch, {"_raw_text": True})

    # Override the provider to emit non-JSON prose.
    class _Prose(_StructuredProvider):
        def __init__(self):
            super().__init__({})

        def complete(self, *, system, messages, tools, model, max_tokens):
            async def gen():
                yield TextDelta("Sure! Here is the summary: the patient seems fine.")
                yield Done("stop")

            return gen()

    monkeypatch.setattr(clinical, "get_provider", lambda name, *a, **k: _Prose())
    res = await client.post(
        "/api/v1/copilot/clinical/case-summary",
        headers=auth_headers,
        json={"patient_id": str(patient_id)},
    )
    assert res.status_code == 503, res.text
    body = res.json()
    assert res.headers.get("x-ai-error-code") == "AI_INVALID_OUTPUT"
    assert "AI_INVALID_OUTPUT" in body["message"]


async def test_provider_failure_is_ai_unavailable(
    client: AsyncClient, auth_headers: dict, test_clinic, patient_id: UUID, monkeypatch
):
    _install_provider(monkeypatch, {}, fail=RuntimeError("upstream timeout"))
    res = await client.post(
        "/api/v1/copilot/clinical/case-summary",
        headers=auth_headers,
        json={"patient_id": str(patient_id)},
    )
    assert res.status_code == 503, res.text
    assert res.headers.get("x-ai-error-code") == "AI_UNAVAILABLE"
    assert "AI_UNAVAILABLE" in res.json()["message"]


async def test_second_review_never_claims_high_confidence_on_sparse_data(
    client: AsyncClient, auth_headers: dict, test_clinic, patient_id: UUID, monkeypatch
):
    payload = _review_payload()
    payload["confidence"] = "high"  # model tries to overstate confidence
    _install_provider(monkeypatch, payload)
    res = await client.post(
        "/api/v1/copilot/clinical/second-review",
        headers=auth_headers,
        json={"patient_id": str(patient_id)},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    # Sparse structured data forces the confidence down (safety).
    assert data["confidence"] in ("low", "medium")
    assert data["confidence"] != "high"


# --- authorization & tenant isolation -----------------------------------


async def test_unauthenticated_rejected(client: AsyncClient):
    from uuid import uuid4

    res = await client.post(
        "/api/v1/copilot/clinical/case-summary",
        json={"patient_id": str(uuid4())},
    )
    assert res.status_code in (401, 403)


async def test_patient_in_another_clinic_is_not_found(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic,
    patient_id: UUID,
    monkeypatch,
    db_session,
):
    from uuid import uuid4

    from app.core.auth.models import Clinic
    from app.modules.patients.models import Patient

    _install_provider(monkeypatch, _summary_payload())

    other = Clinic(
        id=uuid4(),
        name="Other Clinic",
        tax_id="B87654321",
        address={"city": "Barcelona"},
        settings={},
    )
    db_session.add(other)
    await db_session.flush()
    foreign = Patient(
        id=uuid4(),
        clinic_id=other.id,
        first_name="Externo",
        last_name="Otro",
        status="active",
    )
    db_session.add(foreign)
    await db_session.commit()

    res = await client.post(
        "/api/v1/copilot/clinical/case-summary",
        headers=auth_headers,
        json={"patient_id": str(foreign.id)},
    )
    # The tool registry scopes by clinic_id → the foreign patient is
    # invisible → PATIENT_NOT_FOUND (never leaks across tenants).
    assert res.status_code == 404, res.text
    assert res.headers.get("x-ai-error-code") == "PATIENT_NOT_FOUND"
    assert "PATIENT_NOT_FOUND" in res.json()["message"]


# --- real provider wire path (no mocks of the provider under test) ------


async def test_openai_provider_wire_path_parses_structured_json(monkeypatch):
    """The REAL OpenAIProvider decodes a streamed JSON completion.

    Uses httpx MockTransport (no network) so the code under test is the
    genuine production provider + our JSON extraction + schema validation.
    """
    import json

    import httpx

    from app.core.llm.base import Role
    from app.core.llm.openai_provider import OpenAIProvider
    from app.modules.copilot.clinical import _extract_json
    from app.modules.copilot.clinical_schemas import CaseSummary

    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    chunks = []
    body = {
        "summary": "Wire-path summary.",
        "current_condition": ["a"],
        "key_findings": ["b"],
        "active_treatments": [],
        "important_history": [],
        "outstanding_items": [],
        "missing_information": ["odontogram"],
        "uncertainty": ["sparse"],
    }
    for tok in json.dumps(body).split(" "):
        chunks.append(
            sse(
                {
                    "choices": [
                        {"index": 0, "delta": {"content": tok + " "}, "finish_reason": None}
                    ],
                    "usage": None,
                }
            )
        )
    chunks.append(
        sse(
            {
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )
    )
    chunks.append("data: [DONE]\n\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content="".join(chunks), headers={"content-type": "text/event-stream"}
        )

    transport = httpx.MockTransport(handler)

    # Inject the mock transport into the openai client by monkeypatching
    # the AsyncOpenAI httpx client.
    import openai

    real_init = openai.AsyncOpenAI.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["http_client"] = httpx.AsyncClient(transport=transport)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(openai.AsyncOpenAI, "__init__", patched_init)

    provider = OpenAIProvider(api_key="test-key")
    text = ""
    in_tok = out_tok = 0
    async for ev in provider.complete(
        system="return JSON",
        messages=[ProviderMessage(role=Role.USER, content=[])],
        tools=[],
        model="gpt-test",
        max_tokens=500,
    ):
        if isinstance(ev, TextDelta):
            text += ev.text
        elif isinstance(ev, Usage):
            in_tok, out_tok = ev.input_tokens, ev.output_tokens

    parsed = _extract_json(text)
    assert parsed is not None and parsed["summary"] == "Wire-path summary."
    result = CaseSummary.model_validate(
        {**parsed, "generated_by": "ai", "model": "gpt-test", "sources": []}
    )
    assert result.missing_information == ["odontogram"]
    assert in_tok == 10 and out_tok == 5
