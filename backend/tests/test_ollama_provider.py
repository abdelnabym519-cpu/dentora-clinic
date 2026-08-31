"""Ollama provider: factory, configuration and copilot validation.

Ollama reuses the OpenAI-compatible client against its ``/v1`` endpoint
(streaming + tool calling + usage are wire-compatible), so these tests
focus on the seams this integration owns:

* factory resolution of ``"ollama"`` (and that the OpenAI / AI-gateway
  paths are untouched),
* ``OLLAMA_BASE_URL`` / ``COPILOT_MODEL_OLLAMA`` configuration,
* the per-clinic copilot settings validation for the new provider,
* the client-level endpoint + streaming/tool-call event mapping that an
  Ollama deployment exercises.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.base import (
    Done,
    LLMConfigError,
    TextDelta,
    ToolUse,
    Usage,
)
from app.core.llm.factory import SUPPORTED_PROVIDERS, get_provider
from app.core.llm.openai_provider import OpenAIProvider, _uses_completion_tokens
from app.database import engine


class SettingsPatch:
    """Same pattern as test_ai_gateway_client.py — swap settings, restore."""

    def __init__(self, **values):
        self.values = values
        self.original = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.original[key] = getattr(settings, key)
            setattr(settings, key, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.original.items():
            setattr(settings, key, value)


class TestOllamaFactory:
    def test_supported_providers_lists_all_live_providers(self):
        assert SUPPORTED_PROVIDERS == ("openai", "ollama", "cloudflare")

    def test_ollama_default_config_is_empty(self):
        # Backward compatibility: a deployment that sets no OLLAMA env
        # var keeps exactly the previous behavior.
        assert settings.OLLAMA_BASE_URL == ""
        assert settings.COPILOT_MODEL_OLLAMA

    def test_ollama_without_base_url_raises_config_error(self):
        with SettingsPatch(OLLAMA_BASE_URL=""):
            with pytest.raises(LLMConfigError) as exc:
                get_provider("ollama")
        assert "OLLAMA_BASE_URL" in str(exc.value)

    def test_ollama_rejects_whitespace_only_base_url(self):
        with SettingsPatch(OLLAMA_BASE_URL="   "):
            with pytest.raises(LLMConfigError):
                get_provider("ollama")

    def test_ollama_returns_openai_compatible_client_target(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            provider = get_provider("ollama")
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url == "http://ollama.example.test:11434/v1/"

    def test_ollama_trailing_slash_normalization(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1/"):
            provider = get_provider("ollama")
        assert provider._base_url == "http://ollama.example.test:11434/v1/"

    def test_openai_path_unchanged(self):
        # No gateway, key present: same OpenAI client as before the
        # Ollama provider existed (base_url=None -> default OpenAI API).
        with SettingsPatch(
            OPENAI_API_KEY="sk-test",
            LICENSE_ENFORCEMENT=False,
            OLLAMA_BASE_URL="http://ollama.example.test:11434/v1",
        ):
            provider = get_provider("openai")
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url is None
        assert provider._api_key == "sk-test"

    def test_openai_gateway_path_unchanged(self):
        with SettingsPatch(
            LICENSE_ENFORCEMENT=True,
            AI_GATEWAY_BASE_URL="https://ai.example.test/custom/v1",
            LICENSE_SERVER_URL="",
        ):
            provider = get_provider("openai")
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url == "https://ai.example.test/custom/v1/"
        assert provider._api_key_resolver is not None

    def test_unknown_provider_still_rejected(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            with pytest.raises(LLMConfigError) as exc:
                get_provider("anthropic")
        assert "Unsupported LLM provider" in str(exc.value)


class TestOllamaClientEndpoint:
    async def test_ollama_client_targets_configured_endpoint(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            provider = get_provider("ollama")
            client = await provider._client_for_request()
        assert str(client.base_url) == "http://ollama.example.test:11434/v1/"
        # Ollama ignores the header; the client just requires one to exist.
        assert client.api_key == "ollama-local"


# --------------------------------------------------------------------------
# Wire-mapping tests: the exact chunk shapes Ollama's /v1 endpoint emits
# (OpenAI Chat Completions streaming format) must map to neutral events.
# --------------------------------------------------------------------------


class _FakeFunction:
    def __init__(self, name=None, arguments=""):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, index, id_=None, name=None, arguments=""):
        self.index = index
        self.id = id_
        self.function = _FakeFunction(name, arguments)


class _FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeChunk:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    return _FakeChunk([_FakeChoice(_FakeDelta(content, tool_calls), finish_reason)], usage)


def _usage_chunk(prompt_tokens, completion_tokens):
    return _FakeChunk([], usage=_FakeUsage(prompt_tokens, completion_tokens))


class _FakeCompletions:
    def __init__(self, stream):
        self._stream = stream
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._stream


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, stream):
        self.chat = _FakeChat(_FakeCompletions(stream))


def _run_complete(provider, **kwargs):
    async def gather():
        return [event async for event in provider.complete(**kwargs)]

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(gather())
    finally:
        loop.close()


def _base_kwargs(model="llama3.1:8b"):
    return dict(
        system="You are a dental clinic assistant.",
        messages=[],
        tools=[],
        model=model,
        max_tokens=100,
    )


class TestOllamaWireMapping:
    def test_text_stream_maps_to_text_delta_usage_done(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            provider = get_provider("ollama")

        async def stream():
            yield _chunk(content="Hola")
            yield _chunk(content=", doctor.")
            yield _usage_chunk(42, 7)

        provider._client_for_request = _fake_client(stream)
        events = _run_complete(provider, **_base_kwargs())

        assert [type(e) for e in events] == [TextDelta, TextDelta, Usage, Done]
        assert "".join(e.text for e in events[:2]) == "Hola, doctor."
        usage = events[2]
        assert (usage.input_tokens, usage.output_tokens) == (42, 7)
        assert events[3].stop_reason == "stop"

    def test_ollama_model_ids_use_max_tokens_param(self):
        # _uses_completion_tokens() only targets gpt-5/o-series, so every
        # Ollama model id goes through `max_tokens` — the param Ollama's
        # /v1 accepts.
        for model in ("llama3.1:8b", "qwen2.5:7b", "mistral-small", "phi3"):
            assert _uses_completion_tokens(model) is False
        # OpenAI behavior untouched.
        assert _uses_completion_tokens("gpt-5.4-mini") is True

    def test_request_kwargs_for_ollama_model(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            provider = get_provider("ollama")

        async def stream():
            yield _usage_chunk(1, 1)

        client = _FakeClient(stream())

        async def fake_client_for_request():
            return client

        provider._client_for_request = fake_client_for_request
        _run_complete(provider, **_base_kwargs())
        kwargs = client.chat.completions.last_kwargs
        assert kwargs["model"] == "llama3.1:8b"
        assert kwargs["max_tokens"] == 100
        assert kwargs["stream"] is True
        assert kwargs["stream_options"] == {"include_usage": True}

    def test_fragmented_tool_call_maps_to_single_tool_use(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            provider = get_provider("ollama")

        # The model echoes the wire-form name (dots -> hyphens) exactly
        # as it received it in the tool schema.
        async def stream():
            yield _chunk(
                tool_calls=[
                    _FakeToolCall(0, id_="call_1", name="patients-search_patients"),
                    _FakeToolCall(0, arguments='{"que'),
                ]
            )
            yield _chunk(tool_calls=[_FakeToolCall(0, arguments='ry": "Ana"}')])
            yield _chunk(finish_reason="tool_calls")
            yield _usage_chunk(10, 5)

        provider._client_for_request = _fake_client(stream)
        events = _run_complete(
            provider,
            system="You are a dental clinic assistant.",
            messages=[],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "patients.search_patients",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            model="llama3.1:8b",
            max_tokens=100,
        )

        tool_uses = [e for e in events if isinstance(e, ToolUse)]
        assert len(tool_uses) == 1
        tool_use = tool_uses[0]
        assert tool_use.id == "call_1"
        # Wire name round-trips back to the registry's dotted name.
        assert tool_use.name == "patients.search_patients"
        assert tool_use.input == {"query": "Ana"}
        assert [type(e) for e in events] == [Usage, ToolUse, Done]
        assert events[-1].stop_reason == "tool_calls"

    def test_tool_schemas_sent_on_wire_are_name_sanitized(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            provider = get_provider("ollama")

        async def stream():
            yield _usage_chunk(1, 1)

        client = _FakeClient(stream())

        async def fake_client_for_request():
            return client

        provider._client_for_request = fake_client_for_request
        _run_complete(
            provider,
            system="sys",
            messages=[],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "patients.search_patients",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            model="llama3.1:8b",
            max_tokens=100,
        )
        kwargs = client.chat.completions.last_kwargs
        assert kwargs["tools"][0]["function"]["name"] == "patients-search_patients"
        assert kwargs["parallel_tool_calls"] is False


def _fake_client(stream):
    async def fake_client_for_request():
        return _FakeClient(stream())

    return fake_client_for_request


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_pool():
    await engine.dispose()
    yield
    await engine.dispose()


class TestCopilotSettingsValidation:
    async def test_ollama_rejected_when_base_url_not_configured(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        with SettingsPatch(OLLAMA_BASE_URL=""):
            res = await client.patch(
                "/api/v1/copilot/settings",
                headers=auth_headers,
                json={"provider": "ollama"},
            )
        assert res.status_code == 400, res.text
        assert "OLLAMA_BASE_URL" in res.json()["message"]
        # Stored provider is untouched.
        res = await client.get("/api/v1/copilot/settings", headers=auth_headers)
        assert res.json()["data"]["provider"] == "openai"

    async def test_ollama_accepted_when_base_url_configured(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            res = await client.patch(
                "/api/v1/copilot/settings",
                headers=auth_headers,
                json={"provider": "ollama", "model": "llama3.1:8b"},
            )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["provider"] == "ollama"
        assert data["model"] == "llama3.1:8b"

        # New conversations inherit the Ollama provider + model.
        res = await client.post("/api/v1/copilot/sessions", headers=auth_headers, json={})
        assert res.status_code == 201, res.text
        conv = res.json()["data"]
        assert conv["provider"] == "ollama"
        assert conv["model"] == "llama3.1:8b"

        # Back to OpenAI with a key configured still works.
        with SettingsPatch(
            OLLAMA_BASE_URL="http://ollama.example.test:11434/v1",
            OPENAI_API_KEY="sk-test",
        ):
            res = await client.patch(
                "/api/v1/copilot/settings",
                headers=auth_headers,
                json={"provider": "openai", "model": "gpt-5.4-mini"},
            )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["provider"] == "openai"

    async def test_openai_validation_unchanged(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        with SettingsPatch(OPENAI_API_KEY=""):
            res = await client.patch(
                "/api/v1/copilot/settings",
                headers=auth_headers,
                json={"provider": "openai"},
            )
        assert res.status_code == 400, res.text
        assert "OPENAI_API_KEY" in res.json()["message"]
