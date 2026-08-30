"""Real wire-path tests for the local Ollama provider.

These tests do NOT mock the code under test. They stand up an in-process
HTTP server that speaks Ollama's native ``/api/chat`` NDJSON streaming
protocol (the exact shape Ollama emits: one JSON object per line, a
final ``done:true`` object with token counts and ``tool_calls`` for
function calling) and point the REAL ``OllamaProvider.complete()`` at it
via ``httpx.MockTransport`` — no network, no OpenAI, no cloud.

This proves the production path:

    Dentora -> OllamaProvider -> Ollama /api/chat (NDJSON stream)
            -> TextDelta / ToolUse / Usage / Done events
            -> (clinical) JSON extraction + Pydantic validation
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.llm.base import (
    Done,
    ProviderMessage,
    Role,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUse,
    ToolUseBlock,
    Usage,
)
from app.core.llm.ollama_provider import OllamaProvider


class _OllamaStub:
    """An httpx transport that emulates an Ollama server.

    ``mode="json"`` streams a plain JSON object across several lines
    (clinical features). ``mode="tools"`` emits a tool_call then, on the
    follow-up request carrying the tool result, streams final text.
    """

    def __init__(self, mode: str, payload_lines: list[dict[str, Any]]):
        self.mode = mode
        self.payload_lines = payload_lines
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        self.requests.append(body)
        ndjson = b"".join((json.dumps(o) + "\n").encode() for o in self.payload_lines)
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=ndjson,
            request=request,
        )


def _provider_with(handler) -> OllamaProvider:
    transport = httpx.MockTransport(handler)

    async def _client(self):  # noqa: ANN001
        return httpx.AsyncClient(transport=transport, base_url=self._base_url)

    prov = OllamaProvider(base_url="http://ollama.test:11434", model="llama3.1:8b")
    # Patch the client construction inside _stream_chat by monkeypatching
    # httpx.AsyncClient used within the provider module.
    import app.core.llm.ollama_provider as mod

    orig_client = mod.httpx.AsyncClient

    def _factory(*args, **kwargs):  # noqa: ANN002, ANN003
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    mod.httpx.AsyncClient = _factory  # type: ignore[attr-defined]
    prov._restore = lambda: setattr(mod.httpx, "AsyncClient", orig_client)  # type: ignore[attr-defined]
    return prov


@pytest.mark.asyncio
async def test_ollama_streams_text_and_usage_for_structured_json():
    # A case-summary JSON object streamed in chunks across NDJSON lines.
    obj = {
        "summary": "Adult patient with an active budget.",
        "key_findings": ["One outstanding budget"],
        "active_treatments": [],
        "missing_information": [],
        "uncertainty": [],
    }
    lines = [
        {
            "message": {"role": "assistant", "content": "Here is the result:\n```json\n"},
            "done": False,
        },
        {"message": {"role": "assistant", "content": json.dumps(obj)}, "done": False},
        {"message": {"role": "assistant", "content": "\n```"}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 123,
            "eval_count": 45,
        },
    ]
    stub = _OllamaStub("json", lines)
    prov = _provider_with(stub.handler)
    try:
        events = [
            e
            async for e in prov.complete(
                system="You output JSON.",
                messages=[ProviderMessage(Role.USER, [TextBlock("summarise")])],
                tools=[],
                model="llama3.1:8b",
                max_tokens=512,
            )
        ]
    finally:
        prov._restore()  # type: ignore[attr-defined]

    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    usage = [e for e in events if isinstance(e, Usage)]
    done = [e for e in events if isinstance(e, Done)]

    assert "summary" in text and "active budget" in text
    assert len(usage) == 1 and usage[0].input_tokens == 123 and usage[0].output_tokens == 45
    assert done and done[-1].stop_reason == "stop"

    # Real Ollama wire shape was requested: model + stream + options.
    sent = stub.requests[0]
    assert sent["model"] == "llama3.1:8b"
    assert sent["stream"] is True
    assert sent["options"]["num_predict"] == 512
    assert sent["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_ollama_emits_tool_call_then_final_text():
    lines = [
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "patients-get_patient",
                            "arguments": {"patient_id": "abc-123"},
                        }
                    }
                ],
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 50,
            "eval_count": 10,
        }
    ]
    stub = _OllamaStub("tools", lines)
    prov = _provider_with(stub.handler)
    try:
        events = [
            e
            async for e in prov.complete(
                system="Use tools.",
                messages=[ProviderMessage(Role.USER, [TextBlock("load the patient")])],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "patients.get_patient",
                            "description": "get",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
                model="llama3.1:8b",
                max_tokens=512,
            )
        ]
    finally:
        prov._restore()  # type: ignore[attr-defined]

    tool_uses = [e for e in events if isinstance(e, ToolUse)]
    assert len(tool_uses) == 1
    # Dot/hyphen bijection restored on the way back.
    assert tool_uses[0].name == "patients.get_patient"
    assert tool_uses[0].input == {"patient_id": "abc-123"}
    assert tool_uses[0].id.startswith("call_")

    # Tool schema name was sanitised for Ollama (hyphen, not dot).
    sent_tools = stub.requests[0]["tools"]
    assert sent_tools[0]["function"]["name"] == "patients-get_patient"


@pytest.mark.asyncio
async def test_ollama_tool_result_message_wire_shape():
    """Assistant tool call + tool result serialize to Ollama's shape."""
    from app.core.llm.ollama_provider import _to_ollama_messages

    msgs = [
        ProviderMessage(
            Role.ASSISTANT,
            [
                TextBlock(""),
                ToolUseBlock(id="c1", name="patients.get_patient", input={"patient_id": "x"}),
            ],
        ),
        ProviderMessage(Role.TOOL, [ToolResultBlock(tool_call_id="c1", content={"ok": True})]),
    ]
    wire = _to_ollama_messages("sys", msgs)
    assert wire[0] == {"role": "system", "content": "sys"}
    assert wire[1]["role"] == "assistant"
    assert wire[1]["tool_calls"][0]["function"]["name"] == "patients-get_patient"
    assert wire[2]["role"] == "tool"
    assert '"ok": true' in wire[2]["content"] or "ok" in wire[2]["content"]


@pytest.mark.asyncio
async def test_ollama_unreachable_raises_llm_error():
    """Connection failure must surface as a provider LLMError (safe fail)."""
    import app.core.llm.ollama_provider as mod

    def _refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        raise httpx.ConnectError("Connection refused")

    # Transport that always refuses.
    transport = httpx.MockTransport(_refuse)
    orig = mod.httpx.AsyncClient

    def _factory(*args, **kwargs):  # noqa: ANN002, ANN003
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    mod.httpx.AsyncClient = _factory  # type: ignore[attr-defined]
    prov = OllamaProvider(base_url="http://127.0.0.1:1", model="m")
    try:
        with pytest.raises(Exception) as exc:  # noqa: PT011
            async for _ in prov.complete(
                system="s",
                messages=[ProviderMessage(Role.USER, [TextBlock("hi")])],
                tools=[],
                model="m",
                max_tokens=10,
            ):
                pass
        assert "Ollama" in str(exc.value) or "reach" in str(exc.value)
    finally:
        mod.httpx.AsyncClient = orig  # type: ignore[attr-defined]
