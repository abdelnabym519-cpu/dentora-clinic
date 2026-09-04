"""Provider resolution.

v1 resolves ``"openai"`` and ``"ollama"``. Ollama reuses the
OpenAI-compatible client (``OllamaProvider``) against its ``/v1``
endpoint, and ``"cloudflare"`` resolves Cloudflare Workers AI through
the OpenAI-compatible client against its official OpenAI-compatible
endpoint — the orchestrator keeps speaking neutral types; Anthropic
slots in later with no change to callers (``base.py``).
"""

from __future__ import annotations

from app.config import settings
from app.core.llm.base import LLMConfigError, Provider

SUPPORTED_PROVIDERS = ("openai", "ollama", "cloudflare")


def get_provider(name: str, *, api_key: str | None = None) -> Provider:
    """Return a configured :class:`Provider` for ``name``.

    Raises :class:`LLMConfigError` for unsupported names or for a
    provider this deployment is not configured to serve, so a clinic
    can never select a provider that cannot answer.
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

    if name == "cloudflare":
        # Cloudflare Workers AI exposes the OpenAI Chat Completions wire
        # format at https://api.cloudflare.com/<account_id>/ai/v1, so the
        # existing OpenAI-compatible client is reused as-is. The API
        # token doubles as the Bearer credential.
        from app.core.llm.openai_provider import OpenAIProvider

        account_id = settings.CLOUDFLARE_ACCOUNT_ID.strip()
        api_token = settings.CLOUDFLARE_API_TOKEN.strip()
        if not account_id or not api_token:
            raise LLMConfigError(
                "Cloudflare provider requires CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN"
            )

        return OpenAIProvider(
            api_key=api_token,
            base_url=f"https://api.cloudflare.com/{account_id}/ai/v1",
        )

    raise LLMConfigError(
        f"Unsupported LLM provider: {name!r} (supported: {', '.join(SUPPORTED_PROVIDERS)})"
    )


def get_default_model(name: str) -> str:
    """Return the configured default chat model for a provider."""
    if name == "openai":
        return settings.COPILOT_MODEL_CHAT_OPENAI
    if name == "ollama":
        return settings.COPILOT_MODEL_CHAT_OLLAMA
    if name == "cloudflare":
        return settings.CLOUDFLARE_AI_MODEL
    raise LLMConfigError(
        f"Unsupported LLM provider: {name!r} (supported: {', '.join(SUPPORTED_PROVIDERS)})"
    )
