"""Ollama implementation of the neutral :class:`Provider` protocol.

Runs fully local inference through an Ollama server
(https://ollama.com) — no cloud LLM and no API key. It maps the neutral
message/event types in :mod:`app.core.llm.base` to and from Ollama's
native streaming ``/api/chat`` NDJSON API, including tool calls.

Wiring is identical to the OpenAI provider: the orchestrator and the
clinical AI features speak only neutral types, so selecting
``provider="ollama"`` (via ``COPILOT_PROVIDER_DEFAULT`` or a clinic's
copilot settings) is all that is required — nothing above
``app/core/llm/`` changes.

Configuration (env only, no secrets):
    OLLAMA_BASE_URL   default http://localhost:11434
    OLLAMA_MODEL      default llama3.1:8b-instruct-q4_K_M  (any pulled model)

Ollama's chat API reference:
    POST {base_url}/api/chat
    request : {"model", "messages", "stream": true, "tools": [...],
               "options": {"num_predict": N}}
    stream  : NDJSON, one JSON object per line:
                {"message": {"role":"assistant","content":...,
                             "tool_calls":[{"function":{"name","arguments"}}]},
                 "done": false}
              final object: {"done": true, "done_reason": "stop",
                             "prompt_eval_count": N, "eval_count": M}
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.llm.base import (
    Done,
    LLMConfigError,
    LLMError,
    ProviderEvent,
    ProviderMessage,
    Role,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUse,
    ToolUseBlock,
    Usage,
)


# Ollama tool/function names must match ``^[a-zA-Z0-9_]+$``; our registry
# namespaces with a dot (``patients.get_patient``). ``.`` <-> ``-`` is the
# same lossless bijection the OpenAI provider uses.
def _to_ollama_name(qualified: str) -> str:
    return qualified.replace(".", "-")


def _from_ollama_name(safe: str) -> str:
    return safe.replace("-", ".")


class OllamaProvider:
    """Streams completions from a local Ollama server, neutral types."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        think: bool | None = None,
        timeout: float = 180.0,
    ) -> None:
        from app.config import settings

        self._base_url = (
            base_url or getattr(settings, "OLLAMA_BASE_URL", "") or "http://localhost:11434"
        ).rstrip("/")
        self._default_model = (
            model or getattr(settings, "OLLAMA_MODEL", "") or "llama3.1:8b-instruct-q4_K_M"
        )
        self._think = bool(think if think is not None else getattr(settings, "OLLAMA_THINK", False))
        self._timeout = timeout

    async def _stream_chat(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """POST /api/chat and yield each NDJSON line as a dict."""
        url = f"{self._base_url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code == 404:
                        body = await resp.aread()
                        raise LLMError(
                            f"Ollama model not found (is it pulled?): {body.decode('utf-8', 'replace')[:300]}"
                        )
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise LLMError(
                            f"Ollama HTTP {resp.status_code}: {body.decode('utf-8', 'replace')[:300]}"
                        )
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            # Partial/keep-alive line — ignore, never fabricate.
                            continue
        except httpx.HTTPError as exc:  # connection refused, timeout, ...
            raise LLMError(f"Cannot reach Ollama at {self._base_url}: {exc}") from exc

    async def complete(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        wire_messages = _to_ollama_messages(system, messages)
        # ``think`` controls Qwen3 thinking mode: default off so the answer
        # (not a reasoning trace that can consume the whole token budget and
        # leave message.content empty) is returned. Silently ignored by models
        # that do not support thinking.
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": wire_messages,
            "stream": True,
            "think": self._think,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [_sanitize_tool_schema(t) for t in tools]

        stop_reason = "stop"
        usage_emitted = False

        async for obj in self._stream_chat(payload):
            msg = obj.get("message") or {}
            content = msg.get("content")
            if content:
                yield TextDelta(text=content)

            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    args = _parse_args(args)
                if name:
                    # Ollama doesn't stream tool-call ids; synthesise a stable one.
                    yield ToolUse(
                        id=f"call_{abs(hash((name, json.dumps(args, sort_keys=True, default=str)))):x}",
                        name=_from_ollama_name(name),
                        input=args if isinstance(args, dict) else {},
                    )

            if obj.get("done"):
                done_reason = obj.get("done_reason")
                if done_reason:
                    stop_reason = str(done_reason)
                prompt_tokens = obj.get("prompt_eval_count")
                eval_tokens = obj.get("eval_count")
                if (prompt_tokens is not None or eval_tokens is not None) and not usage_emitted:
                    yield Usage(
                        input_tokens=int(prompt_tokens or 0),
                        output_tokens=int(eval_tokens or 0),
                    )
                    usage_emitted = True

        yield Done(stop_reason=stop_reason)


def _sanitize_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI-shaped tool spec to Ollama's tool shape.

    OpenAI: {"type":"function","function":{"name","description","parameters"}}
    Ollama: {"type":"function","function":{"name","description","parameters"}}
    (same envelope) — only the name needs the dot->hyphen bijection.
    """
    fn = dict(tool.get("function", {}))
    fn["name"] = _to_ollama_name(fn.get("name", ""))
    out = dict(tool)
    out["function"] = fn
    return out


def _parse_args(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stringify(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _join_text(msg: ProviderMessage) -> str:
    return "".join(b.text for b in msg.content if isinstance(b, TextBlock))


def _to_ollama_messages(system: str, messages: list[ProviderMessage]) -> list[dict[str, Any]]:
    """Flatten neutral messages into Ollama's /api/chat wire shape.

    Tool results are appended as a ``tool`` role message; Ollama accepts
    ``role: "tool"`` with ``tool_name``/``content``. We fold each tool
    result block into its own message so multi-tool turns stay legible.
    """
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})

    for msg in messages:
        if msg.role == Role.USER:
            out.append({"role": "user", "content": _join_text(msg)})

        elif msg.role == Role.ASSISTANT:
            text = _join_text(msg)
            tool_calls = [
                {
                    "function": {
                        "name": _to_ollama_name(block.name),
                        "arguments": block.input if isinstance(block.input, dict) else {},
                    }
                }
                for block in msg.content
                if isinstance(block, ToolUseBlock)
            ]
            wire: dict[str, Any] = {"role": "assistant", "content": text or ""}
            if tool_calls:
                wire["tool_calls"] = tool_calls
            out.append(wire)

        elif msg.role == Role.TOOL:
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    out.append(
                        {
                            "role": "tool",
                            "content": _stringify(block.content),
                        }
                    )

    return out


__all__ = ["OllamaProvider", "LLMConfigError"]
