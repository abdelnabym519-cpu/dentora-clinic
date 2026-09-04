"""End-to-end: clinical AI runs against a REAL local OpenAI-compatible server.

Dentora's ``OllamaProvider`` subclasses ``OpenAIProvider`` and talks to
Ollama's **OpenAI-compatible** endpoint (``{OLLAMA_BASE_URL}/chat/completions``,
SSE), not Ollama's native ``/api/chat`` NDJSON API. This harness therefore
emulates the ``/v1`` wire format.

    HTTP POST /api/v1/copilot/clinical/*
      -> clinical.py -> get_provider("ollama")
      -> OllamaProvider (OpenAIProvider subclass)
      -> http://127.0.0.1:<port>/v1/chat/completions  (SSE)

A real socket is bound on a real port and the real provider factory is used
(no provider injection, no monkeypatched transport), so this exercises the
actual network path an Ollama deployment takes.

This file replaces the donor's ``test_ollama_e2e.py``, which emulated the
native ``/api/chat`` NDJSON protocol and was hard-bound to the older Ollama
provider implementation that the consolidation did not take.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.config import settings
from app.core.llm.factory import get_provider
from app.database import engine
from app.modules.copilot import clinical
from tests.test_copilot_clinical_ai import (
    _intel_payload,
    _plan_payload,
    _report_payload,
    _review_payload,
    _summary_payload,
)

# The running stub returns whichever payload is currently active.
_ACTIVE_PAYLOAD: dict[str, Any] = _summary_payload()

_MODEL = "llama3.1:8b"


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def _sse(obj: dict[str, Any]) -> bytes:
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


def _openai_compatible_app(state: dict[str, Any]):
    """ASGI app emulating the OpenAI /v1/chat/completions SSE endpoint."""

    async def app(scope, receive, send):  # noqa: ANN001
        if scope["type"] != "http" or not scope["path"].endswith("/chat/completions"):
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"not found"})
            return

        chunks: list[bytes] = []
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
                if not msg.get("more_body"):
                    break
        body = json.loads(b"".join(chunks).decode())
        state["requests"].append(body)
        state["paths"].append(scope["path"])

        content = json.dumps(_ACTIVE_PAYLOAD)
        half = len(content) // 2
        base = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "model": _MODEL}

        payloads = [
            {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
            {**base, "choices": [{"index": 0, "delta": {"content": content[:half]}}]},
            {**base, "choices": [{"index": 0, "delta": {"content": content[half:]}}]},
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {
                **base,
                "choices": [],
                "usage": {"prompt_tokens": 200, "completion_tokens": 120, "total_tokens": 320},
            },
        ]
        out = b"".join(_sse(p) for p in payloads) + b"data: [DONE]\n\n"

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send({"type": "http.response.body", "body": out})

    return app


@pytest_asyncio.fixture
async def ollama_server(monkeypatch):
    """Start a real-socket OpenAI-compatible server and point settings at it."""
    import uvicorn

    state: dict[str, Any] = {"requests": [], "paths": []}

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(
        uvicorn.Config(
            _openai_compatible_app(state),
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)

    base = f"http://127.0.0.1:{port}/v1/"
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", base, raising=False)
    monkeypatch.setattr(settings, "OLLAMA_MODEL", _MODEL, raising=False)
    monkeypatch.setattr(settings, "COPILOT_PROVIDER_DEFAULT", "ollama", raising=False)
    monkeypatch.setattr(settings, "COPILOT_MODEL_CHAT_OLLAMA", _MODEL, raising=False)
    # Clinical layer must resolve the real factory (no provider injection).
    monkeypatch.setattr(clinical, "get_provider", get_provider)

    yield state

    server.should_exit = True
    thread.join(timeout=5)


@pytest_asyncio.fixture
async def ollama_patient(client: AsyncClient, auth_headers: dict, test_clinic) -> UUID:
    res = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": "Pablo", "last_name": "Fernández", "phone": "+34612345001"},
    )
    assert res.status_code in (200, 201), res.text
    return UUID(res.json()["data"]["id"])


ENDPOINTS = [
    ("/api/v1/copilot/clinical/case-summary", _summary_payload, "summary"),
    ("/api/v1/copilot/clinical/report", _report_payload, "overview"),
    ("/api/v1/copilot/clinical/second-review", _review_payload, "overall_impression"),
    ("/api/v1/copilot/clinical/treatment-suggestions", _plan_payload, "suggested_order"),
    ("/api/v1/copilot/clinical/case-intelligence", _intel_payload, "insights"),
]


@pytest.mark.parametrize(("path", "payload_fn", "field"), ENDPOINTS)
async def test_clinical_feature_runs_via_real_openai_compatible_server(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic,
    ollama_server,
    ollama_patient: UUID,
    path,
    payload_fn,
    field,
):
    import tests.test_ollama_v1_e2e as mod

    expected = payload_fn()
    mod._ACTIVE_PAYLOAD = expected

    # Sanity: the real factory hands back an OllamaProvider pointed at our
    # local server (not OpenAI, not Cloudflare).
    provider = get_provider("ollama")
    assert type(provider).__name__ == "OllamaProvider"
    assert provider._base_url.startswith("http://127.0.0.1:")

    res = await client.post(path, headers=auth_headers, json={"patient_id": str(ollama_patient)})
    assert res.status_code == 200, f"{path}: {res.text}"
    data = res.json()["data"]

    assert data["generated_by"] == "ai"
    assert data["model"] == _MODEL  # local Ollama model echoed
    assert data[field] == expected[field]
    assert any(s == "patients.get_patient" for s in data["sources"])

    # A real HTTP request reached the server over the socket, on the
    # OpenAI-compatible path.
    assert len(ollama_server["requests"]) >= 1
    assert ollama_server["paths"][-1].endswith("/chat/completions")
    sent = ollama_server["requests"][-1]
    assert sent["model"] == _MODEL
    assert sent["stream"] is True
    # The provider picks `max_completion_tokens` for GPT-5/o-series and the
    # legacy `max_tokens` for everything else (an Ollama model here).
    token_param = "max_completion_tokens" if "max_completion_tokens" in sent else "max_tokens"
    assert sent[token_param] > 0, sent


async def test_reasoning_effort_none_is_sent_to_the_server(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic,
    ollama_server,
    ollama_patient: UUID,
):
    """Regression guard for the empty-content failure mode.

    Qwen3-family models "think" by default: the reasoning trace can consume
    the whole token budget and leave ``content`` empty, so the stream ends
    with no text and no error. The canonical provider suppresses this by
    sending ``reasoning_effort: "none"`` via ``extra_body`` (the /v1
    equivalent of Ollama's native ``think: false``). Assert it really goes
    out on the wire.
    """
    import tests.test_ollama_v1_e2e as mod

    mod._ACTIVE_PAYLOAD = _summary_payload()

    res = await client.post(
        "/api/v1/copilot/clinical/case-summary",
        headers=auth_headers,
        json={"patient_id": str(ollama_patient)},
    )
    assert res.status_code == 200, res.text

    sent = ollama_server["requests"][-1]
    assert sent.get("reasoning_effort") == "none", sent
