"""Ollama implementation through its OpenAI-compatible endpoint."""

from __future__ import annotations

from app.core.llm.openai_provider import OpenAIProvider


class OllamaProvider(OpenAIProvider):
    """Local Ollama provider speaking Dentora's neutral Provider protocol."""

    def __init__(
        self,
        *,
        base_url: str | None = "http://host.docker.internal:11434/v1/",
        timeout: float | None = None,
    ) -> None:
        # An empty/whitespace OLLAMA_BASE_URL means "no explicit override":
        # the provider resolves without a custom base rather than raising at
        # factory time. Non-empty values keep the /v1 anchoring below.
        super().__init__(
            api_key="ollama-local",
            base_url=self._normalize_base_url(base_url) if base_url and base_url.strip() else None,
            extra_body={"reasoning_effort": "none"},
            timeout=timeout,
        )

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """Anchor the OpenAI-compatible base at Ollama's ``/v1`` path.

        The OpenAI client appends ``chat/completions`` to this base, so a
        host-level value such as ``http://host.docker.internal:11434``
        would otherwise target ``/chat/completions`` — a path Ollama does
        not serve, answered with a plain-text ``404 page not found``.
        Accept host-level and ``/v1``-suffixed values alike.
        """
        normalized = url.strip().rstrip("/")
        if not normalized.endswith("/v1"):
            normalized = f"{normalized}/v1"
        return f"{normalized}/"
