"""Provider resolution.

v1 resolves ``"openai"`` only. Anthropic / Ollama slot in here later
with no change to callers — the orchestrator already speaks neutral
types (``base.py``).
"""

from __future__ import annotations

from app.config import settings
from app.core.llm.base import LLMConfigError, Provider

SUPPORTED_PROVIDERS = ("openai", "ollama")


def get_provider(name: str, *, api_key: str | None = None) -> Provider:
    """Return a configured :class:`Provider` for ``name``.

    Raises :class:`LLMConfigError` for unsupported names so a clinic can
    never select a provider this deployment cannot serve.
    """
    if name == "ollama":
        from app.core.llm.ollama_provider import OllamaProvider

        return OllamaProvider(base_url=settings.OLLAMA_BASE_URL)

    if name == "openai":
        from app.core.llm.openai_provider import OpenAIProvider

        if settings.LICENSE_ENFORCEMENT:
            from app.core.license.service import license_manager

            base_url = settings.ai_gateway_base_url

            if not base_url:
                raise LLMConfigError("AI gateway is not configured")

            return OpenAIProvider(
                base_url=base_url,
                api_key_resolver=license_manager.get_ai_gateway_credential,
            )

        return OpenAIProvider(api_key=api_key or settings.OPENAI_API_KEY)

    raise LLMConfigError(
        f"Unsupported LLM provider: {name!r} (supported: {', '.join(SUPPORTED_PROVIDERS)})"
    )


def get_default_model(name: str) -> str:
    """Return the configured default chat model for a provider."""
    if name == "openai":
        return settings.COPILOT_MODEL_CHAT_OPENAI
    if name == "ollama":
        return settings.COPILOT_MODEL_CHAT_OLLAMA
    raise LLMConfigError(
        f"Unsupported LLM provider: {name!r} (supported: {', '.join(SUPPORTED_PROVIDERS)})"
    )
