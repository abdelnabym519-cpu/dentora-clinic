"""Regression: the Ollama provider anchors its base URL at Ollama's /v1.

The OpenAI-compatible client appends ``chat/completions`` to the base
URL verbatim, so ``OLLAMA_BASE_URL=http://host.docker.internal:11434``
(a natural deployment value) previously produced
``POST /chat/completions`` — answered by Ollama with a plain-text
``404 page not found``. Every accepted spelling must land on
``/v1/chat/completions``.
"""

import pytest

from app.core.llm.ollama_provider import OllamaProvider


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://host.docker.internal:11434", "http://host.docker.internal:11434/v1/"),
        ("http://host.docker.internal:11434/", "http://host.docker.internal:11434/v1/"),
        ("http://host.docker.internal:11434/v1", "http://host.docker.internal:11434/v1/"),
        ("http://host.docker.internal:11434/v1/", "http://host.docker.internal:11434/v1/"),
        ("http://192.168.1.10:11434", "http://192.168.1.10:11434/v1/"),
    ],
)
def test_base_url_always_targets_ollama_openai_compat_path(raw: str, expected: str) -> None:
    provider = OllamaProvider(base_url=raw)
    assert provider._base_url == expected
    # The exact wire target the OpenAI client will build:
    assert f"{provider._base_url}chat/completions" == f"{expected}chat/completions"


def test_default_base_url_targets_openai_compat_path() -> None:
    provider = OllamaProvider()
    assert provider._base_url == "http://host.docker.internal:11434/v1/"


def test_provider_forwards_bounded_timeout() -> None:
    """A stalled Ollama must not hang on the SDK's very long default:
    the configured bound is forwarded to the OpenAI client."""
    from app.config import settings
    from app.core.llm.factory import get_provider

    provider = get_provider("ollama")
    assert provider._timeout == settings.COPILOT_TIMEOUT_SECONDS
    assert settings.COPILOT_TIMEOUT_SECONDS > 0

    bounded = OllamaProvider(base_url="http://127.0.0.1:11434", timeout=15)
    assert bounded._timeout == 15
