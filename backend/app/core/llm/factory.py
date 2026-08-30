"""Provider resolution.

Resolves the cloud ``"openai"`` provider and the fully local
``"ollama"`` provider (no API key, runs on an Ollama server). Adding a
vendor is a single branch here — callers already speak neutral types
(``base.py``).
"""

from __future__ import annotations

from app.config import settings
from app.core.llm.base import LLMConfigError, Provider

SUPPORTED_PROVIDERS = ("openai", "ollama")


def default_model_for(provider: str) -> str:
    """Return the deployment's default model id for ``provider``.

    Keeps provider/model selection coherent: a clinic that switches to
    the local ``ollama`` provider gets a local Ollama model rather than
    a cloud model id the Ollama server cannot serve.
    """
    if provider == "ollama":
        return settings.COPILOT_MODEL_CHAT_OLLAMA
    return settings.COPILOT_MODEL_CHAT_OPENAI


def get_provider(name: str, *, api_key: str | None = None) -> Provider:
    """Return a configured :class:`Provider` for ``name``.

    Raises :class:`LLMConfigError` for unsupported names so a clinic can
    never select a provider this deployment cannot serve.
    """
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

    if name == "ollama":
        # Fully local inference via an Ollama server. No API key, no cloud
        # LLM: the base URL and model come from env/settings only.
        from app.core.llm.ollama_provider import OllamaProvider

        return OllamaProvider(
            base_url=settings.OLLAMA_BASE_URL or None,
            model=settings.OLLAMA_MODEL or None,
        )

    raise LLMConfigError(
        f"Unsupported LLM provider: {name!r} (supported: {', '.join(SUPPORTED_PROVIDERS)})"
    )
