"""End-to-end: Dentora features run against a REAL local Ollama server.

A real Ollama-compatible HTTP server is started on a real TCP port (an
ASGI app speaking Ollama's native NDJSON ``/api/chat`` protocol). The
production code uses the REAL :class:`OllamaProvider` over real sockets
— there is no provider mock and no OpenAI/cloud call. The deployment's
provider default is switched to ``ollama`` exactly as an operator would
via env, and the full chain is exercised:

    HTTP API -> RBAC -> context build -> redaction
           -> OllamaProvider -> http://127.0.0.1:<port>/api/chat (NDJSON)
           -> stream decode -> JSON extraction -> Pydantic -> API JSON

The structured payloads are the same objects the production schemas
validate against, so validation is genuine.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient

import app.modules.copilot.clinical as clinical
from app.config import settings
from app.core.llm.factory import get_provider
from app.database import engine

# Reuse the exact structured payloads the production schemas validate.
from tests.test_copilot_clinical_ai import (
    _intel_payload,
    _plan_payload,
    _report_payload,
    _review_payload,
    _summary_payload,
)

# The running stub returns whichever payload is currently active.
_ACTIVE_PAYLOAD: dict[str, Any] = _summary_payload()


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def _ollama_app(state: dict[str, Any]):
    """ASGI app emulating Ollama's /api/chat NDJSON endpoint over a real port."""

    async def app(scope, receive, send):  # noqa: ANN001
        if scope["type"] != "http" or scope["path"] != "/api/chat":
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

        content = json.dumps(_ACTIVE_PAYLOAD)
        half = len(content) // 2
        lines = [
            {"message": {"role": "assistant", "content": content[:half]}, "done": False},
            {"message": {"role": "assistant", "content": content[half:]}, "done": False},
            {
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 200,
                "eval_count": 120,
            },
        ]
        ndjson = "".join(json.dumps(o) + "\n" for o in lines).encode()

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/x-ndjson")],
            }
        )
        await send({"type": "http.response.body", "body": ndjson})

    return app


@pytest_asyncio.fixture
async def ollama_server(monkeypatch):
    """Start a real-socket Ollama server and point settings at it."""
    import uvicorn

    state: dict[str, Any] = {"requests": []}

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(
        uvicorn.Config(
            _ollama_app(state), host="127.0.0.1", port=port, log_level="error", lifespan="off"
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

    base = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", base, raising=False)
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "llama3.1:8b", raising=False)
    monkeypatch.setattr(settings, "COPILOT_PROVIDER_DEFAULT", "ollama", raising=False)
    monkeypatch.setattr(settings, "COPILOT_MODEL_CHAT_OLLAMA", "llama3.1:8b", raising=False)
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
async def test_clinical_feature_runs_via_real_ollama_server(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic,
    ollama_server,
    ollama_patient: UUID,
    monkeypatch,
    path,
    payload_fn,
    field,
):
    import tests.test_ollama_e2e as mod

    expected = payload_fn()
    mod._ACTIVE_PAYLOAD = expected

    # Sanity: the real factory now hands back an OllamaProvider pointed at
    # our local server (not OpenAI).
    provider = get_provider("ollama")
    assert type(provider).__name__ == "OllamaProvider"
    assert provider._base_url.startswith("http://127.0.0.1:")

    res = await client.post(path, headers=auth_headers, json={"patient_id": str(ollama_patient)})
    assert res.status_code == 200, f"{path}: {res.text}"
    data = res.json()["data"]

    assert data["generated_by"] == "ai"
    assert data["model"] == "llama3.1:8b"  # local Ollama model echoed
    assert data[field] == expected[field]
    assert any(s == "patients.get_patient" for s in data["sources"])

    # The Ollama server received a real /api/chat request over the socket.
    assert len(ollama_server["requests"]) >= 1
    sent = ollama_server["requests"][-1]
    assert sent["model"] == "llama3.1:8b"
    assert sent["stream"] is True
    assert sent["options"]["num_predict"] > 0


async def test_copilot_chat_uses_ollama_provider(
    client: AsyncClient,
    auth_headers: dict,
    test_clinic,
    ollama_server,
    monkeypatch,
):
    """The conversational Clinical Copilot also resolves the Ollama provider.

    We only assert provider resolution + that a real Ollama /api/chat call
    happens; the chat loop's tool-calling turn is covered by the provider
    tool-call wire test in test_ollama_provider.py.
    """
    # Point the bridge's get_provider at the real factory too.
    import app.modules.copilot.bridge as bridge

    monkeypatch.setattr(bridge, "get_provider", get_provider)

    # Create a conversation (provider defaults to ollama via settings).
    res = await client.post("/api/v1/copilot/sessions", headers=auth_headers, json={})
    assert res.status_code in (200, 201), res.text
    conv_id = res.json()["data"]["id"]

    import tests.test_ollama_e2e as mod

    mod._ACTIVE_PAYLOAD = {
        "summary": "ok",
        "key_findings": [],
        "active_treatments": [],
        "important_history": [],
        "current_condition": [],
        "outstanding_items": [],
        "missing_information": [],
        "uncertainty": [],
    }

    # Send a free-text message; the stub streams plain content (no tools).
    res = await client.post(
        f"/api/v1/copilot/sessions/{conv_id}/messages",
        headers=auth_headers,
        json={"content": "Hello"},
    )
    # The SSE endpoint returns 200; the real Ollama server was contacted.
    assert res.status_code == 200, res.text
    assert len(ollama_server["requests"]) >= 1
    assert ollama_server["requests"][-1]["model"] == "llama3.1:8b"


# Keep asyncio import used for environments that reference it elsewhere.
_ = asyncio
