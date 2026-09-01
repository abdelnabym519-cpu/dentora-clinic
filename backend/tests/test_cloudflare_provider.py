"""Cloudflare Workers AI provider: factory, configuration, validation.

Cloudflare reuses the OpenAI-compatible client against its official
OpenAI-compatible endpoint ``https://api.cloudflare.com/<account_id>/ai/v1``
(streaming + tool calling + usage are wire-compatible), so these tests
focus on the seams this integration owns:

* factory resolution of ``"cloudflare"`` (and that the OpenAI / Ollama
  paths are untouched),
* ``CLOUDFLARE_ACCOUNT_ID`` / ``CLOUDFLARE_API_TOKEN`` /
  ``CLOUDFLARE_AI_MODEL`` configuration,
* the per-clinic copilot settings validation + provider switching for
  the new provider (configuration-driven, no code change),
* the client-level endpoint + streaming/tool-call event mapping that a
  Cloudflare deployment exercises — unit level (fake client) and
  integration level (in-process OpenAI-compatible server, real
  ``openai`` SDK + httpx + SSE),
* opt-in live checks against the real Workers AI (skipped unless
  ``CLOUDFLARE_ACCOUNT_ID`` + ``CLOUDFLARE_API_TOKEN`` are in the
  environment).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import pytest_asyncio
from httpx import AsyncClient
from openai import AuthenticationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.base import (
    Done,
    LLMConfigError,
    ProviderMessage,
    Role,
    TextBlock,
    TextDelta,
    ToolUse,
    Usage,
)
from app.core.llm.factory import SUPPORTED_PROVIDERS, get_provider
from app.core.llm.openai_provider import OpenAIProvider, _uses_completion_tokens
from app.database import engine

CF_ACCOUNT = "acc-test-123"
CF_TOKEN = "cf-test-token"
CF_MODEL = "@cf/meta/llama-3.1-8b-instruct"


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


class TestCloudflareFactory:
    def test_supported_providers_lists_openai_ollama_and_cloudflare(self):
        assert SUPPORTED_PROVIDERS == ("openai", "ollama", "cloudflare")

    def test_cloudflare_default_config_is_empty(self):
        # Backward compatibility: a deployment that sets no Cloudflare
        # env var keeps exactly the previous behavior.
        assert settings.CLOUDFLARE_ACCOUNT_ID == ""
        assert settings.CLOUDFLARE_API_TOKEN == ""
        assert settings.CLOUDFLARE_AI_MODEL.startswith("@cf/")

    def test_cloudflare_without_account_id_raises_config_error(self):
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID="", CLOUDFLARE_API_TOKEN="tok"):
            with pytest.raises(LLMConfigError) as exc:
                get_provider("cloudflare")
        assert "CLOUDFLARE_ACCOUNT_ID" in str(exc.value)

    def test_cloudflare_without_api_token_raises_config_error(self):
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID="acc-1", CLOUDFLARE_API_TOKEN=""):
            with pytest.raises(LLMConfigError) as exc:
                get_provider("cloudflare")
        assert "CLOUDFLARE_API_TOKEN" in str(exc.value)

    def test_cloudflare_rejects_whitespace_only_credentials(self):
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID="   ", CLOUDFLARE_API_TOKEN="  "):
            with pytest.raises(LLMConfigError):
                get_provider("cloudflare")

    def test_cloudflare_returns_openai_compatible_client_target(self):
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID=CF_ACCOUNT, CLOUDFLARE_API_TOKEN=CF_TOKEN):
            provider = get_provider("cloudflare")
        assert isinstance(provider, OpenAIProvider)
        # Official OpenAI-compatible endpoint, derived from the account id.
        assert provider._base_url == f"https://api.cloudflare.com/{CF_ACCOUNT}/ai/v1/"

    def test_cloudflare_account_id_whitespace_stripped(self):
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID=f" {CF_ACCOUNT} ", CLOUDFLARE_API_TOKEN=CF_TOKEN):
            provider = get_provider("cloudflare")
        assert provider._base_url == f"https://api.cloudflare.com/{CF_ACCOUNT}/ai/v1/"

    def test_openai_path_unchanged(self):
        # No gateway, key present: same OpenAI client as before the
        # Cloudflare provider existed (base_url=None -> default OpenAI API).
        with SettingsPatch(OPENAI_API_KEY="sk-test", LICENSE_ENFORCEMENT=False):
            provider = get_provider("openai")
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url is None
        assert provider._api_key == "sk-test"

    def test_ollama_path_unchanged(self):
        with SettingsPatch(OLLAMA_BASE_URL="http://ollama.example.test:11434/v1"):
            provider = get_provider("ollama")
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url == "http://ollama.example.test:11434/v1/"
        assert provider._api_key == "ollama-local"

    def test_unknown_provider_still_rejected(self):
        with pytest.raises(LLMConfigError) as exc:
            get_provider("anthropic")
        assert "Unsupported LLM provider" in str(exc.value)
        # The error lists every live provider, so operators see the
        # full set of options.
        for p in ("openai", "ollama", "cloudflare"):
            assert p in str(exc.value)


class TestCloudflareClientAuth:
    async def test_cloudflare_client_targets_account_endpoint_with_token(self):
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID=CF_ACCOUNT, CLOUDFLARE_API_TOKEN=CF_TOKEN):
            provider = get_provider("cloudflare")
            client = await provider._client_for_request()
        assert str(client.base_url) == f"https://api.cloudflare.com/{CF_ACCOUNT}/ai/v1/"
        # The Workers AI API token IS the Bearer credential.
        assert client.api_key == CF_TOKEN


# --------------------------------------------------------------------------
# Wire-mapping tests: the exact chunk shapes Cloudflare's OpenAI-compatible
# endpoint emits must map to neutral events.
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


def _base_kwargs(model=CF_MODEL):
    return dict(
        system="You are a dental clinic assistant.",
        messages=[],
        tools=[],
        model=model,
        max_tokens=100,
    )


def _cf_provider():
    with SettingsPatch(CLOUDFLARE_ACCOUNT_ID=CF_ACCOUNT, CLOUDFLARE_API_TOKEN=CF_TOKEN):
        return get_provider("cloudflare")


def _fake_client(stream):
    async def fake_client_for_request():
        return _FakeClient(stream())

    return fake_client_for_request


class TestCloudflareWireMapping:
    def test_text_stream_maps_to_text_delta_usage_done(self):
        provider = _cf_provider()

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

    def test_cloudflare_model_ids_use_max_tokens_param(self):
        # _uses_completion_tokens() only targets gpt-5/o-series, so every
        # Cloudflare model id goes through `max_tokens` — the param the
        # Workers AI OpenAI-compatible endpoint accepts.
        for model in (
            "@cf/meta/llama-3.1-8b-instruct",
            "@cf/meta/llama-3.3-70b-instruct",
            "@cf/mistralai/mistral-small-3.1-24b-instruct",
            "@cf/qwen/qwen2.5-7b-instruct",
        ):
            assert _uses_completion_tokens(model) is False
        # OpenAI behavior untouched.
        assert _uses_completion_tokens("gpt-5.4-mini") is True

    def test_request_kwargs_for_cloudflare_model(self):
        provider = _cf_provider()

        async def stream():
            yield _usage_chunk(1, 1)

        client = _FakeClient(stream())

        async def fake_client_for_request():
            return client

        provider._client_for_request = fake_client_for_request
        _run_complete(provider, **_base_kwargs())
        kwargs = client.chat.completions.last_kwargs
        # Model ids pass through verbatim (no remapping for @cf/... ids).
        assert kwargs["model"] == CF_MODEL
        assert kwargs["max_tokens"] == 100
        assert kwargs["stream"] is True
        assert kwargs["stream_options"] == {"include_usage": True}

    def test_fragmented_tool_call_maps_to_single_tool_use(self):
        provider = _cf_provider()

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
            model=CF_MODEL,
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
        provider = _cf_provider()

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
            model=CF_MODEL,
            max_tokens=100,
        )
        kwargs = client.chat.completions.last_kwargs
        assert kwargs["tools"][0]["function"]["name"] == "patients-search_patients"
        assert kwargs["parallel_tool_calls"] is False


# --------------------------------------------------------------------------
# Integration tests: an in-process OpenAI-compatible server stands in for
# the Workers AI endpoint. The real `openai` SDK client (httpx, SSE
# parsing, auth header) runs against it over actual HTTP — everything
# except the remote endpoint itself is exercised for real.
# --------------------------------------------------------------------------


STUB_ACCOUNT = "acc-stub"
STUB_TOKEN = "cf-stub-token"


def _sse_frame(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _text_frames(model: str) -> list[bytes]:
    def chunk(delta: dict, finish=None, usage=None) -> bytes:
        payload = {
            "id": "chatcmpl-stub",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if usage is not None:
            payload["usage"] = usage
        return _sse_frame(payload)

    return [
        chunk({"role": "assistant", "content": "Hola"}),
        chunk({"content": ", doctor."}),
        chunk({}, finish="stop"),
        chunk({}, usage={"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49}),
        b"data: [DONE]\n\n",
    ]


def _tool_frames(model: str) -> list[bytes]:
    def chunk(delta: dict, finish=None, usage=None) -> bytes:
        payload = {
            "id": "chatcmpl-stub",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if usage is not None:
            payload["usage"] = usage
        return _sse_frame(payload)

    return [
        chunk(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "patients-search_patients"},
                    }
                ],
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"que'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'ry": "Ana"}'}}]}),
        chunk({}, finish="tool_calls"),
        chunk({}, usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
        b"data: [DONE]\n\n",
    ]


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        server: _StubServer = self.server
        server.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})

        expected_path = f"/{server.account_id}/ai/v1/chat/completions"
        if self.path != expected_path:
            self._json(404, {"error": {"message": "not found"}})
            return
        if self.headers.get("Authorization") != f"Bearer {STUB_TOKEN}":
            # Same 401 shape Workers AI returns for a bad token.
            self._json(401, {"error": {"message": "invalid api key"}})
            return

        frames = (
            _tool_frames(body["model"])
            if body["model"].endswith("-tools")
            else _text_frames(body["model"])
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for frame in frames:
            self.wfile.write(frame)
            self.wfile.flush()
            time.sleep(0.005)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _StubServer(ThreadingHTTPServer):
    account_id: str = STUB_ACCOUNT
    requests: list[dict] = []


@pytest.fixture()
def cf_stub():
    server = _StubServer(("127.0.0.1", 0), _StubHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _stub_provider(server: _StubServer, token: str = STUB_TOKEN) -> OpenAIProvider:
    with SettingsPatch(CLOUDFLARE_ACCOUNT_ID=STUB_ACCOUNT, CLOUDFLARE_API_TOKEN=token):
        provider = get_provider("cloudflare")
    # Retarget the factory-built client at the in-process stub, keeping
    # the exact endpoint path shape (/{account}/ai/v1) so the SDK's URL
    # assembly is exercised against the real endpoint layout.
    provider._base_url = f"http://127.0.0.1:{server.server_address[1]}/{STUB_ACCOUNT}/ai/v1/"
    return provider


class TestCloudflareStubIntegration:
    async def test_text_streaming_over_real_http_sends_bearer_token(self, cf_stub):
        provider = _stub_provider(cf_stub)
        events = [
            ev
            async for ev in provider.complete(
                system="You are a dental clinic assistant.",
                messages=[],
                tools=[],
                model=CF_MODEL,
                max_tokens=100,
            )
        ]
        assert [type(e) for e in events] == [TextDelta, TextDelta, Usage, Done]
        assert "".join(e.text for e in events[:2]) == "Hola, doctor."
        assert (events[2].input_tokens, events[2].output_tokens) == (42, 7)

        req = cf_stub.requests[-1]
        assert req["path"] == f"/{STUB_ACCOUNT}/ai/v1/chat/completions"
        headers = {k.lower(): v for k, v in req["headers"].items()}
        assert headers["authorization"] == f"Bearer {STUB_TOKEN}"
        assert req["body"]["model"] == CF_MODEL
        assert req["body"]["stream"] is True
        assert req["body"]["stream_options"] == {"include_usage": True}
        assert req["body"]["max_tokens"] == 100

    async def test_tool_call_over_real_http(self, cf_stub):
        provider = _stub_provider(cf_stub)
        events = [
            ev
            async for ev in provider.complete(
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
                model="stub-7b-tools",
                max_tokens=100,
            )
        ]
        tool_uses = [e for e in events if isinstance(e, ToolUse)]
        assert len(tool_uses) == 1
        assert tool_uses[0].name == "patients.search_patients"
        assert tool_uses[0].input == {"query": "Ana"}
        assert events[-1].stop_reason == "tool_calls"

        req = cf_stub.requests[-1]
        assert req["body"]["tools"][0]["function"]["name"] == "patients-search_patients"
        assert req["body"]["parallel_tool_calls"] is False

    async def test_wrong_token_yields_authentication_error(self, cf_stub):
        provider = _stub_provider(cf_stub, token="wrong-token")
        with pytest.raises(AuthenticationError):
            async for _ in provider.complete(
                system="s",
                messages=[],
                tools=[],
                model=CF_MODEL,
                max_tokens=100,
            ):
                pass


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_pool():
    await engine.dispose()
    yield
    await engine.dispose()


# --------------------------------------------------------------------------
# Per-clinic copilot settings: validation, provider switching and
# backward compatibility through the real API.
# --------------------------------------------------------------------------


class TestCopilotSettingsCloudflare:
    async def test_cloudflare_rejected_when_credentials_not_configured(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID="", CLOUDFLARE_API_TOKEN=""):
            res = await client.patch(
                "/api/v1/copilot/settings",
                headers=auth_headers,
                json={"provider": "cloudflare"},
            )
        assert res.status_code == 400, res.text
        assert "CLOUDFLARE_ACCOUNT_ID" in res.json()["message"]
        # Stored provider is untouched.
        res = await client.get("/api/v1/copilot/settings", headers=auth_headers)
        assert res.json()["data"]["provider"] == "openai"

    async def test_cloudflare_accepted_when_credentials_configured(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID="acc-1", CLOUDFLARE_API_TOKEN="tok-1"):
            res = await client.patch(
                "/api/v1/copilot/settings",
                headers=auth_headers,
                json={"provider": "cloudflare", "model": settings.CLOUDFLARE_AI_MODEL},
            )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["provider"] == "cloudflare"
        assert data["model"] == settings.CLOUDFLARE_AI_MODEL

        # New conversations inherit the Cloudflare provider + model.
        res = await client.post("/api/v1/copilot/sessions", headers=auth_headers, json={})
        assert res.status_code == 201, res.text
        conv = res.json()["data"]
        assert conv["provider"] == "cloudflare"
        assert conv["model"] == settings.CLOUDFLARE_AI_MODEL

    async def test_provider_switching_is_configuration_driven(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        # With every provider configured, clinics may move between
        # openai / ollama / cloudflare in any order — configuration
        # only, no code change.
        with SettingsPatch(
            CLOUDFLARE_ACCOUNT_ID="acc-1",
            CLOUDFLARE_API_TOKEN="tok-1",
            OPENAI_API_KEY="sk-test",
            OLLAMA_BASE_URL="http://ollama.example.test:11434/v1",
        ):
            for provider, model in (
                ("cloudflare", settings.CLOUDFLARE_AI_MODEL),
                ("openai", "gpt-5.4-mini"),
                ("ollama", "llama3.1:8b"),
                ("cloudflare", "custom-cf-model"),
            ):
                res = await client.patch(
                    "/api/v1/copilot/settings",
                    headers=auth_headers,
                    json={"provider": provider, "model": model},
                )
                assert res.status_code == 200, res.text
                data = res.json()["data"]
                assert data["provider"] == provider
                assert data["model"] == model

    async def test_default_provider_cloudflare_when_deployment_default(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        with SettingsPatch(
            COPILOT_PROVIDER_DEFAULT="cloudflare",
            CLOUDFLARE_ACCOUNT_ID="acc-1",
            CLOUDFLARE_API_TOKEN="tok-1",
        ):
            res = await client.get("/api/v1/copilot/settings", headers=auth_headers)
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["provider"] == "cloudflare"
        assert data["model"] == settings.CLOUDFLARE_AI_MODEL

    async def test_openai_default_unchanged_when_cloudflare_unconfigured(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        # Backward compatibility: a deployment with no Cloudflare env
        # vars behaves exactly as before this integration.
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID="", CLOUDFLARE_API_TOKEN=""):
            res = await client.get("/api/v1/copilot/settings", headers=auth_headers)
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["provider"] == "openai"
        assert data["model"] == settings.COPILOT_MODEL_CHAT_OPENAI

    async def test_unconfigured_provider_surfaces_sse_error_event(
        self, db_session: AsyncSession, client: AsyncClient, auth_headers: dict, test_clinic
    ) -> None:
        # Error/fallback: a clinic saved on Cloudflare whose deployment
        # later loses its credentials must fail gracefully as an SSE
        # error event — never a 500 mid-stream, never a silent hang.
        with SettingsPatch(CLOUDFLARE_ACCOUNT_ID="acc-1", CLOUDFLARE_API_TOKEN="tok-1"):
            res = await client.patch(
                "/api/v1/copilot/settings",
                headers=auth_headers,
                json={"provider": "cloudflare"},
            )
            assert res.status_code == 200, res.text
        res = await client.post("/api/v1/copilot/sessions", headers=auth_headers, json={})
        assert res.status_code == 201, res.text
        conv_id = res.json()["data"]["id"]

        res = await client.post(
            f"/api/v1/copilot/sessions/{conv_id}/messages",
            headers=auth_headers,
            json={"content": "hola"},
        )
        assert res.status_code == 200, res.text
        assert "event: error" in res.text
        assert "CLOUDFLARE_ACCOUNT_ID" in res.text


# --------------------------------------------------------------------------
# Opt-in live checks against the real Cloudflare Workers AI. Skipped
# unless the environment actually has credentials — never claimed as
# verified otherwise.
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not (settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_API_TOKEN),
    reason="CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set",
)
class TestCloudflareLive:
    async def test_live_streaming_against_workers_ai(self) -> None:
        provider = get_provider("cloudflare")
        events: list = [
            ev
            async for ev in provider.complete(
                system="You are a dental clinic assistant.",
                messages=[
                    ProviderMessage(
                        role=Role.USER,
                        content=[TextBlock(text="Say 'hello clinic' and nothing else.")],
                    )
                ],
                tools=[],
                model=settings.CLOUDFLARE_AI_MODEL,
                max_tokens=100,
            )
        ]
        text = "".join(e.text for e in events if isinstance(e, TextDelta))
        assert text.strip(), "no text streamed from Workers AI"
        assert any(isinstance(e, Done) for e in events)

    async def test_live_tool_call_against_workers_ai(self) -> None:
        provider = get_provider("cloudflare")
        events: list = [
            ev
            async for ev in provider.complete(
                system="You are a dental clinic assistant.",
                messages=[
                    ProviderMessage(
                        role=Role.USER,
                        content=[
                            TextBlock(text="Look up the patient named Ana using the search tool.")
                        ],
                    )
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "patients.search_patients",
                            "parameters": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                        },
                    }
                ],
                model=settings.CLOUDFLARE_AI_MODEL,
                max_tokens=100,
            )
        ]
        tool_uses = [e for e in events if isinstance(e, ToolUse)]
        assert tool_uses, "Workers AI did not emit a tool call"
        assert tool_uses[0].name == "patients.search_patients"
