"""Ollama implementation through its OpenAI-compatible endpoint."""

from __future__ import annotations

from app.core.llm.openai_provider import OpenAIProvider


class OllamaProvider(OpenAIProvider):
    """Local Ollama provider speaking Dentora's neutral Provider protocol."""

    def __init__(
        self,
        *,
        base_url: str = "http://host.docker.internal:11434/v1/",
    ) -> None:
        super().__init__(
            api_key="ollama-local",
            base_url=base_url,
            extra_body={"reasoning_effort": "none"},
        )
