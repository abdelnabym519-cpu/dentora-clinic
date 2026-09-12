#!/usr/bin/env python3
"""Diagnose the LLM provider a deployment resolves — and *why* it fails.

Every clinical-AI endpoint (case summary, case intelligence, treatment
planning, second review, clinical report, copilot) goes through
``app/core/llm``. When that layer cannot reach a provider the UI can only
say "unavailable", which does not distinguish the four things that actually
break a local stack:

1. the resolved provider is not the one you think (env default, or a stale
   per-clinic ``copilot_settings`` row that was lazily created earlier);
2. the container cannot resolve/reach the host (``host.docker.internal``
   needs a ``host-gateway`` mapping on Docker Engine, and Ollama must not
   be bound to ``127.0.0.1``);
3. the model was never pulled (Ollama answers 404 for an unknown model);
4. the provider answers but the request itself fails.

This script checks 1-3 passively and, with ``--probe``, proves 4 by running
one real completion through the same provider object production uses.

Usage (from inside the backend container, so the check reflects what the
application actually sees)::

    docker compose exec backend python -m scripts.diagnose_ai_provider
    docker compose exec backend python -m scripts.diagnose_ai_provider --probe
    docker compose exec backend python -m scripts.diagnose_ai_provider --db

On the host, point it at the same URL the container would use::

    cd backend && OLLAMA_BASE_URL=http://127.0.0.1:11434/v1/ \
        python -m scripts.diagnose_ai_provider --probe

Exit status is 0 when the provider is usable, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.core.llm.base import LLMError, ProviderMessage, Role, TextBlock, TextDelta, Usage
from app.core.llm.factory import SUPPORTED_PROVIDERS, get_default_model, get_provider

PROBE_PROMPT = "Reply with exactly one word: ok"


@dataclass
class Report:
    """Findings collected across the checks, plus the derived verdict."""

    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def healthy(self) -> bool:
        return not self.failures


def _head(title: str) -> None:
    print(f"\n[{title}]")


def _line(label: str, value: str, *, status: str = " ") -> None:
    print(f"  {status} {label:<34} {value}")


# --- 1. configuration -----------------------------------------------------


def resolved_provider() -> tuple[str, str]:
    """Return ``(provider, source)`` mirroring the runtime resolution order.

    The per-clinic ``copilot_settings`` row wins when one exists (checked by
    ``--db``); otherwise ``settings.resolved_copilot_provider`` decides, from
    an explicit ``COPILOT_PROVIDER_DEFAULT`` or from ``ENVIRONMENT``.
    """
    explicit = settings.COPILOT_PROVIDER_DEFAULT.strip()
    if explicit:
        return explicit, f"COPILOT_PROVIDER_DEFAULT (explicit: {explicit!r})"
    derived = settings.resolved_copilot_provider
    return derived, f"ENVIRONMENT={settings.ENVIRONMENT!r} (derived, no explicit override)"


def check_configuration(report: Report) -> tuple[str, str]:
    _head("1. Configuration")
    provider, source = resolved_provider()
    _line("ENVIRONMENT", settings.ENVIRONMENT)
    _line("COPILOT_PROVIDER_DEFAULT", repr(settings.COPILOT_PROVIDER_DEFAULT) or "''")
    _line("resolved provider", provider, status=">" )
    _line("  ...because", source)

    if provider not in SUPPORTED_PROVIDERS:
        report.fail(
            f"Resolved provider {provider!r} is unsupported "
            f"(supported: {', '.join(SUPPORTED_PROVIDERS)})."
        )
        return provider, ""

    try:
        model = get_default_model(provider)
    except LLMError as exc:
        report.fail(str(exc))
        return provider, ""

    _line("default model", model or "(empty)")
    if not model:
        report.fail(f"No model configured for provider {provider!r}.")

    if provider == "ollama":
        _line("OLLAMA_BASE_URL", settings.OLLAMA_BASE_URL)
        _line("COPILOT_TIMEOUT_SECONDS", str(settings.COPILOT_TIMEOUT_SECONDS))
        if "localhost" in settings.OLLAMA_BASE_URL or "127.0.0.1" in settings.OLLAMA_BASE_URL:
            report.warn(
                "OLLAMA_BASE_URL points at localhost/127.0.0.1. Inside a container that is "
                "the container itself, not the host — use host.docker.internal "
                "(mapped by the compose `extra_hosts: host.docker.internal:host-gateway` entry)."
            )
    elif provider == "openai":
        _line("OPENAI_API_KEY", "set" if settings.OPENAI_API_KEY.strip() else "EMPTY")
        if not settings.OPENAI_API_KEY.strip() and not settings.LICENSE_ENFORCEMENT:
            report.fail(
                "Provider is 'openai' but OPENAI_API_KEY is empty — every AI call will fail. "
                "Either set the key, or unset COPILOT_PROVIDER_DEFAULT so a non-production "
                "ENVIRONMENT resolves the local Ollama provider."
            )
    elif provider == "cloudflare":
        _line("CLOUDFLARE_ACCOUNT_ID", "set" if settings.CLOUDFLARE_ACCOUNT_ID.strip() else "EMPTY")
        _line("CLOUDFLARE_API_TOKEN", "set" if settings.CLOUDFLARE_API_TOKEN.strip() else "EMPTY")
        if not settings.CLOUDFLARE_ACCOUNT_ID.strip() or not settings.CLOUDFLARE_API_TOKEN.strip():
            report.fail(
                "Provider is 'cloudflare' but CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN are "
                "not set, so the provider raises LLMConfigError before any request."
            )

    return provider, model


# --- 2. network path ------------------------------------------------------


def check_network(report: Report, base_url: str) -> str | None:
    """Resolve and connect to the provider host. Returns the reachable host."""
    _head("2. Network path")
    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        report.fail(f"Cannot parse a host out of base URL {base_url!r}.")
        return None

    _line("target", f"{parsed.scheme}://{host}:{port}")
    try:
        infos = socket.getaddrinfo(host, None)
        addresses = sorted({info[4][0] for info in infos})
        _line("DNS", ", ".join(addresses), status="+")
    except socket.gaierror as exc:
        _line("DNS", f"FAILED ({exc})", status="x")
        report.fail(
            f"{host} does not resolve here. On Docker Engine `host.docker.internal` only "
            "resolves when the service declares `extra_hosts: "
            '["host.docker.internal:host-gateway"]` (now present in docker-compose.yml). '
            "After changing compose, recreate the container: docker compose up -d backend."
        )
        return None

    try:
        with socket.create_connection((host, port), timeout=5):
            _line("TCP connect", "open", status="+")
    except TimeoutError:
        _line("TCP connect", "TIMEOUT", status="x")
        report.fail(
            f"Connection to {host}:{port} timed out — a firewall is dropping packets. "
            "Allow the Docker subnet to reach that port."
        )
        return None
    except OSError as exc:
        _line("TCP connect", f"REFUSED ({exc})", status="x")
        report.fail(
            f"Nothing is accepting connections on {host}:{port}. If this is Ollama: start it, "
            "and make sure it listens beyond loopback — the default binds 127.0.0.1 only, "
            "which a container cannot reach. Restart it with OLLAMA_HOST=0.0.0.0."
        )
        return None
    return host


# --- 3. model availability ------------------------------------------------


def _model_present(required: str, available: list[str]) -> bool:
    """Match Ollama's tag conventions: ``qwen3:8b`` also satisfies ``qwen3``."""
    if not required:
        return True
    exact = {name.lower() for name in available}
    if required.lower() in exact:
        return True
    stem = required.split(":", 1)[0].lower()
    return any(name.split(":", 1)[0].lower() == stem for name in available)


def check_models(report: Report, base_url: str, model: str, provider: str) -> None:
    _head("3. Models offered by the provider")
    url = base_url.rstrip("/") + "/models"
    headers: dict[str, str] = {}
    if provider == "openai" and settings.OPENAI_API_KEY.strip():
        headers["Authorization"] = f"Bearer {settings.OPENAI_API_KEY.strip()}"
    elif provider == "cloudflare" and settings.CLOUDFLARE_API_TOKEN.strip():
        headers["Authorization"] = f"Bearer {settings.CLOUDFLARE_API_TOKEN.strip()}"

    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        _line("GET /models", f"FAILED ({type(exc).__name__})", status="x")
        report.fail(f"Could not query {url}: {exc}")
        return

    if response.status_code != 200:
        _line("GET /models", f"HTTP {response.status_code}", status="x")
        report.fail(f"{url} returned HTTP {response.status_code}: {response.text[:300]}")
        return

    try:
        payload = response.json()
    except ValueError:
        report.fail(f"{url} did not return JSON: {response.text[:200]}")
        return

    available = [item.get("id", "") for item in payload.get("data", []) if item.get("id")]
    _line("GET /models", f"HTTP 200, {len(available)} model(s)", status="+")
    _line("available", ", ".join(available) if available else "(none)")
    if not available:
        report.fail(
            "The provider is reachable but serves no models. For Ollama: `ollama pull "
            f"{model or '<model>'}`."
        )
        return

    if _model_present(model, available):
        _line(f"required {model!r}", "present", status="+")
    else:
        _line(f"required {model!r}", "MISSING", status="x")
        report.fail(
            f"Model {model!r} is not available at {base_url}. Pull it (`ollama pull {model}`) "
            f"or point the model setting at one of: {', '.join(available)}. Ollama answers "
            "404 for an unpulled model, which surfaces as LLMUnavailableError."
        )


# --- 4. end-to-end probe --------------------------------------------------


async def _probe(provider_name: str, model: str) -> tuple[str, int]:
    """Run one real completion through the production provider object."""
    provider = get_provider(provider_name)
    text_parts: list[str] = []
    tokens = 0
    stream = provider.complete(
        system="You are a connectivity probe. Answer with a single word.",
        messages=[ProviderMessage(role=Role.USER, content=[TextBlock(text=PROBE_PROMPT)])],
        tools=[],
        model=model,
        max_tokens=16,
    )
    try:
        async for event in stream:
            if isinstance(event, TextDelta):
                text_parts.append(event.text)
            elif isinstance(event, Usage):
                tokens = event.input_tokens + event.output_tokens
    finally:
        # Close the generator (and the HTTP response behind it) before the
        # loop shuts down, otherwise asyncio finalizes it at exit and prints
        # teardown tracebacks that look like a failure.
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()
    return "".join(text_parts).strip(), tokens


def _ignore_asyncgen_teardown(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Swallow httpx/httpcore's noisy async-generator teardown at shutdown.

    Closing a streamed response while the loop shuts down makes httpcore
    raise ``RuntimeError('generator didn't stop after athrow()')`` from the
    asyncgen finalizer. It is cosmetic — the completion already finished and
    the exit status reflects the real outcome — but printed next to a healthy
    report it looks like a failure, which is precisely the confusion this
    script exists to remove. Only that one message is filtered; every other
    loop error still reaches the default handler.
    """
    if "closing of asynchronous generator" in str(context.get("message", "")):
        return
    loop.default_exception_handler(context)


async def _probe_quiet(provider_name: str, model: str) -> tuple[str, int]:
    asyncio.get_running_loop().set_exception_handler(_ignore_asyncgen_teardown)
    return await _probe(provider_name, model)


def check_probe(report: Report, provider_name: str, model: str) -> None:
    _head("4. End-to-end probe")
    try:
        text, tokens = asyncio.run(_probe_quiet(provider_name, model))
    except LLMError as exc:
        _line("completion", f"{type(exc).__name__}", status="x")
        print(f"    {exc}")
        report.fail(f"The real provider call failed with {type(exc).__name__} (see above).")
        return
    except Exception as exc:  # noqa: BLE001 - a probe must never mask the cause
        _line("completion", f"UNEXPECTED {type(exc).__name__}", status="x")
        print(f"    {exc}")
        report.fail(
            f"The provider call raised {type(exc).__name__}, which is not part of the neutral "
            "LLM error hierarchy — that would surface to the UI as an opaque 500."
        )
        return

    if not text:
        _line("completion", "empty response", status="!")
        report.fail("The provider returned no text. Check the model serves chat completions.")
        return
    _line("completion", f"{tokens} tokens" if tokens else "streamed", status="+")
    _line("model said", text[:120] or "(empty)", status="+")


# --- 5. per-clinic override -----------------------------------------------


async def _load_clinic_overrides() -> list[tuple[str, str, str]]:
    from sqlalchemy import select

    from app.database import async_session_maker
    from app.modules.copilot.models import CopilotSettings

    async with async_session_maker() as session:
        rows = (await session.execute(select(CopilotSettings))).scalars().all()
        return [(str(row.clinic_id), row.provider, row.model) for row in rows]


def check_database_override(report: Report, env_provider: str) -> None:
    _head("5. Per-clinic override (copilot_settings)")
    print("  The clinic's own row wins over the environment. A row created before the")
    print("  provider default changed keeps its old value — that is the usual reason an")
    print("  env fix appears to do nothing.")
    try:
        rows = asyncio.run(_load_clinic_overrides())
    except Exception as exc:  # noqa: BLE001 - the DB may legitimately be unreachable
        _line("query", f"skipped ({type(exc).__name__})", status="!")
        report.warn("Could not read copilot_settings (database unreachable from here).")
        return

    if not rows:
        _line("rows", "none (the env-derived provider applies)", status="+")
        return

    for clinic_id, provider, model in rows:
        marker = "+" if provider == env_provider else "!"
        _line(f"clinic {clinic_id[:8]}", f"provider={provider} model={model}", status=marker)
        if provider != env_provider:
            report.fail(
                f"Clinic {clinic_id} is pinned to provider={provider!r} model={model!r}, which "
                f"overrides the environment-resolved {env_provider!r}. Rows are lazy-created "
                "and never re-derived, so an old row survives a config change. Update it in "
                "Settings > AI, or: UPDATE copilot_settings SET provider="
                f"'{env_provider}', model='{get_default_model(env_provider)}' WHERE "
                f"clinic_id='{clinic_id}';"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="diagnose_ai_provider",
        description="Report which LLM provider this deployment resolves and why it fails.",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="run one real completion through the production provider object",
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help="also inspect the per-clinic copilot_settings override (needs the database)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="diagnose this provider instead of the resolved one "
        f"({', '.join(SUPPORTED_PROVIDERS)})",
    )
    args = parser.parse_args(argv)

    report = Report()
    print("=" * 78)
    print("Dentora AI provider diagnosis")
    print("=" * 78)

    provider, model = check_configuration(report)
    if args.provider:
        provider = args.provider
        model = get_default_model(provider)
        _line("override --provider", f"{provider} / {model}", status=">")

    base_url = {
        "ollama": settings.OLLAMA_BASE_URL,
        "openai": settings.ai_gateway_base_url or "https://api.openai.com/v1/",
        "cloudflare": (
            f"https://api.cloudflare.com/{settings.CLOUDFLARE_ACCOUNT_ID.strip()}/ai/v1"
            if settings.CLOUDFLARE_ACCOUNT_ID.strip()
            else ""
        ),
    }.get(provider, "")

    if base_url:
        host = check_network(report, base_url)
        if host:
            check_models(report, base_url, model, provider)
    else:
        _head("2. Network path")
        report.fail(f"No base URL is configured for provider {provider!r}.")

    if args.probe and report.healthy:
        check_probe(report, provider, model)
    elif args.probe:
        _head("4. End-to-end probe")
        print("  skipped — fix the failures above first.")

    if args.db:
        check_database_override(report, provider)

    print("\n" + "=" * 78)
    for warning in report.warnings:
        print(f"WARN  {warning}")
    if report.healthy:
        scope = "with a real completion" if args.probe else "for configuration and reachability"
        print(f"VERDICT  {provider}/{model or '?'} is usable {scope}.")
        if not args.probe:
            print("         Re-run with --probe to prove one real completion end to end.")
        print("=" * 78)
        return 0

    for failure in report.failures:
        print(f"FAIL  {failure}")
    print(f"VERDICT  {provider}/{model or '?'} is NOT usable — see the failures above.")
    print("=" * 78)
    return 1


if __name__ == "__main__":
    sys.exit(main())
