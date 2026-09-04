"""OpenAI embedding adapter, intentionally separate from chat-completion logic."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.llm.base import LLMConfigError


class OpenAIEmbeddingProvider:
    """External embedding provider. Callers must pass the privacy gate."""

    name = "openai"
    is_external = True

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        api_key_resolver: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        if not api_key and api_key_resolver is None:
            raise LLMConfigError("OpenAI embedding provider requires OPENAI_API_KEY")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/" if base_url else None
        self._api_key_resolver = api_key_resolver

    async def _client_for_request(self):
        api_key = self._api_key
        if self._api_key_resolver is not None:
            api_key = await self._api_key_resolver()
        if not api_key:
            raise LLMConfigError("AI provider credential is unavailable")

        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return AsyncOpenAI(**kwargs)

    async def embed(
        self,
        texts: list[str],
        *,
        model: str,
        dimensions: int,
    ) -> list[list[float]]:
        client = await self._client_for_request()
        response = await client.embeddings.create(
            input=texts,
            model=model,
            dimensions=dimensions,
            encoding_format="float",
        )
        return [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]
