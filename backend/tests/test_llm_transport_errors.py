"""Transport failures must surface as actionable 503s, never an opaque 500.

The reported symptom behind the "Ollama connection" problem was a bare
*Connection error* in the UI. Its mechanism: ``openai.APIConnectionError``
escaped :class:`OpenAIProvider`, no router caught it (they only catch
``LLMConfigError`` / ``LLMError``), FastAPI answered 500, and the actual
cause — which host, refused vs unresolvable vs unpulled model — was lost.

These tests pin the neutral translation and, just as importantly, the class
relationship that makes the *existing* router handlers do the right thing
without any router change: :class:`LLMUnavailableError` is an
:class:`LLMConfigError`, so it lands on the ``503 +
<module>_provider_unavailable`` branch and ``detail.message`` carries the
remediation.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.config import settings
from app.core.llm.base import (
    LLMConfigError,
    LLMError,
    LLMProviderError,
    LLMUnavailableError,
)
from app.core.llm.openai_provider import OpenAIProvider

BASE_URL = "http://host.docker.internal:11434/v1/"
MODEL = "qwen3:8b"


class SettingsPatch:
    """Same pattern as test_ollama_provider.py — swap settings, restore."""

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


# --- Fakes ----------------------------------------------------------------


class _Completions:
    """``client.chat.completions.create`` that fails at call time or mid-stream."""

    def __init__(self, *, fail_on_create=None, fail_while_streaming=None):
        self._fail_on_create = fail_on_create
        self._fail_while_streaming = fail_while_streaming
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._fail_on_create is not None:
            raise self._fail_on_create
        return self

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        if self._fail_while_streaming is not None:
            raise self._fail_while_streaming
            yield  # pragma: no cover - keeps this an async generator
        yield _chunk("ok")


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions):
        self.chat = _Chat(completions)
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1


def _chunk(content: str):
    class _Delta:
        def __init__(self):
            self.content = content
            self.tool_calls = None

    class _Choice:
        def __init__(self):
            self.delta = _Delta()
            self.finish_reason = "stop"

    class _Chunk:
        def __init__(self):
            self.choices = [_Choice()]
            # The provider inspects `chunk.usage` on every chunk; the real SDK
            # always sets it (None except on the final usage-only chunk).
            self.usage = None

    return _Chunk()


def _provider_with(client: _FakeClient, *, base_url: str = BASE_URL) -> OpenAIProvider:
    provider = OpenAIProvider(api_key="test-key", base_url=base_url, timeout=5.0)

    async def fake_client_for_request():
        return client

    provider._client_for_request = fake_client_for_request
    return provider


def _run(provider) -> list:
    async def gather():
        return [event async for event in provider.complete(
            system="You are a dental clinic assistant.",
            messages=[],
            tools=[],
            model=MODEL,
            max_tokens=100,
        )]

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(gather())
    finally:
        loop.close()


def _status_error(status_code: int, message: str) -> APIStatusError:
    request = httpx.Request("POST", BASE_URL + "chat/completions")
    body = {"error": {"message": message}}
    response = httpx.Response(status_code, request=request, json=body)
    return APIStatusError(message, response=response, body=body)


# --- Error hierarchy ------------------------------------------------------


class TestHierarchy:
    def test_unavailable_is_a_config_error_so_routers_answer_503(self):
        """The whole fix rests on this: routers catch ``LLMConfigError`` and
        return ``503 + <module>_provider_unavailable`` with ``str(exc)`` as
        the message. An unreachable provider must take that branch."""
        assert issubclass(LLMUnavailableError, LLMConfigError)
        assert issubclass(LLMUnavailableError, LLMError)

    def test_provider_error_is_an_llm_error_but_not_a_config_error(self):
        """A provider that answered with a 5xx is an output/upstream problem
        (502), not a deployment misconfiguration (503)."""
        assert issubclass(LLMProviderError, LLMError)
        assert not issubclass(LLMProviderError, LLMConfigError)


# --- Translation ----------------------------------------------------------


class TestTransportTranslation:
    def test_connection_refused_becomes_unavailable_with_remediation(self):
        request = httpx.Request("POST", BASE_URL + "chat/completions")
        client = _FakeClient(_Completions(fail_on_create=APIConnectionError(request=request)))
        provider = _provider_with(client)

        with pytest.raises(LLMUnavailableError) as excinfo:
            _run(provider)

        message = str(excinfo.value)
        # names where it tried, and each thing the operator has to check
        assert BASE_URL.rstrip("/") in message
        assert MODEL in message
        assert "OLLAMA_HOST=0.0.0.0" in message
        assert "host.docker.internal" in message
        assert f"ollama pull {MODEL}" in message

    def test_timeout_becomes_unavailable(self):
        request = httpx.Request("POST", BASE_URL + "chat/completions")
        client = _FakeClient(_Completions(fail_on_create=APITimeoutError(request=request)))
        provider = _provider_with(client)

        with pytest.raises(LLMUnavailableError) as excinfo:
            _run(provider)

        assert "timed out" in str(excinfo.value)
        assert "5.0" in str(excinfo.value)  # the configured bound, not the SDK default

    def test_unpulled_model_404_names_ollama_pull(self):
        """Ollama answers 404 for a model that was never pulled. That is a
        deployment gap the operator can fix in one command, so it must not be
        reported as a generic upstream failure."""
        error = _status_error(404, f"model '{MODEL}' not found, try pulling it first")
        client = _FakeClient(_Completions(fail_on_create=error))
        provider = _provider_with(client)

        with pytest.raises(LLMUnavailableError) as excinfo:
            _run(provider)

        message = str(excinfo.value)
        assert f"ollama pull {MODEL}" in message
        assert "COPILOT_MODEL_CHAT_OLLAMA" in message

    def test_server_error_stays_a_provider_error(self):
        error = _status_error(500, "internal error")
        client = _FakeClient(_Completions(fail_on_create=error))
        provider = _provider_with(client)

        with pytest.raises(LLMProviderError) as excinfo:
            _run(provider)

        assert not isinstance(excinfo.value, LLMUnavailableError)
        assert "500" in str(excinfo.value)

    def test_failure_mid_stream_is_also_translated(self):
        """A dropped connection after the first chunk must not escape raw."""
        request = httpx.Request("POST", BASE_URL + "chat/completions")
        client = _FakeClient(
            _Completions(fail_while_streaming=APIConnectionError(request=request))
        )
        provider = _provider_with(client)

        with pytest.raises(LLMUnavailableError):
            _run(provider)

    def test_real_unreachable_endpoint_raises_unavailable(self):
        """No fakes: the actual SDK against a port nothing listens on."""
        provider = OpenAIProvider(
            api_key="test-key", base_url="http://127.0.0.1:1/v1/", timeout=2.0
        )

        with pytest.raises(LLMUnavailableError):
            _run(provider)


# --- Client lifecycle -----------------------------------------------------


class TestClientLifecycle:
    def test_client_is_closed_after_a_successful_completion(self):
        """``_client_for_request`` builds a client per call, so the completion
        owns its lifecycle; without closing it every AI call leaks an httpx
        connection pool."""
        client = _FakeClient(_Completions())
        provider = _provider_with(client)

        events = _run(provider)

        assert client.close_calls == 1
        assert events, "the happy path must still stream events"

    def test_client_is_closed_when_the_request_fails(self):
        request = httpx.Request("POST", BASE_URL + "chat/completions")
        client = _FakeClient(_Completions(fail_on_create=APIConnectionError(request=request)))
        provider = _provider_with(client)

        with pytest.raises(LLMUnavailableError):
            _run(provider)

        assert client.close_calls == 1


# --- Environment-derived provider -----------------------------------------


class TestEnvironmentDerivedProvider:
    """A fresh local stack used to resolve ``openai`` with an empty
    ``OPENAI_API_KEY`` — every AI endpoint failed before reaching a model.
    The environment now decides unless the operator pins a provider."""

    def test_development_defaults_to_local_ollama(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="", ENVIRONMENT="development"):
            assert settings.resolved_copilot_provider == "ollama"

    def test_unset_environment_defaults_to_local_ollama(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="", ENVIRONMENT="staging"):
            assert settings.resolved_copilot_provider == "ollama"

    def test_production_defaults_to_cloudflare(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="", ENVIRONMENT="production"):
            assert settings.resolved_copilot_provider == "cloudflare"

    def test_explicit_setting_wins_over_the_environment(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="openai", ENVIRONMENT="production"):
            assert settings.resolved_copilot_provider == "openai"
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="ollama", ENVIRONMENT="production"):
            assert settings.resolved_copilot_provider == "ollama"

    def test_whitespace_only_setting_is_treated_as_unset(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="   ", ENVIRONMENT="development"):
            assert settings.resolved_copilot_provider == "ollama"

    def test_production_environment_value_is_case_insensitive(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="", ENVIRONMENT="Production"):
            assert settings.resolved_copilot_provider == "cloudflare"
