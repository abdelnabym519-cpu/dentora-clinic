"""OpenAI implementation of the neutral :class:`Provider` protocol.

v1 ships this provider only. It maps the neutral message/event types in
``base.py`` to and from the OpenAI Chat Completions streaming API.

Tool calling is forced single (``parallel_tool_calls=False``) so the
orchestrator can apply its one-tool-per-turn inline-confirmation model
without juggling partially-resolved tool batches.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.llm.base import (
    Done,
    LLMConfigError,
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


class OpenAIProvider:
    """Streams completions from OpenAI, speaking neutral types."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        api_key_resolver: Callable[[], Awaitable[str]] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        if not api_key and api_key_resolver is None:
            raise LLMConfigError("OpenAI provider requires OPENAI_API_KEY")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/" if base_url else None
        self._api_key_resolver = api_key_resolver
        self._extra_body = extra_body or {}

    async def _client_for_request(self):
        api_key = self._api_key

        if self._api_key_resolver is not None:
            api_key = await self._api_key_resolver()

        if not api_key:
            raise LLMConfigError("AI provider credential is unavailable")

        # Imported lazily so the dependency is only needed when the
        # provider is actually used.
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": api_key}

        if self._base_url:
            kwargs["base_url"] = self._base_url

        return AsyncOpenAI(**kwargs)

    async def complete(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        tools: list[dict],
        model: str,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        wire_messages = _to_openai_messages(system, messages)
        # The GPT-5 / o-series models reject the legacy `max_tokens` param and
        # require `max_completion_tokens`. Older chat models still take
        # `max_tokens`.
        token_param = "max_completion_tokens" if _uses_completion_tokens(model) else "max_tokens"
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": wire_messages,
            token_param: max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "dentora_structured_response",
                    "schema": response_schema,
                },
            }

        if tools:
            kwargs["tools"] = [_sanitize_tool_schema(t) for t in tools]
            kwargs["parallel_tool_calls"] = False
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body

        # index -> {"id": str, "name": str, "args": str}
        pending: dict[int, dict[str, str]] = {}
        stop_reason = "stop"

        client = await self._client_for_request()
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            # The usage-only final chunk carries no choices.
            if chunk.usage is not None:
                yield Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                )
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            if delta is not None and delta.content:
                yield TextDelta(text=delta.content)

            if delta is not None and delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = pending.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function is not None:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["args"] += tc.function.arguments

            if choice.finish_reason:
                stop_reason = choice.finish_reason

        for slot in pending.values():
            yield ToolUse(
                id=slot["id"],
                name=_from_openai_name(slot["name"]),
                input=_parse_args(slot["args"]),
            )

        yield Done(stop_reason=stop_reason)


# OpenAI restricts function names to ``^[a-zA-Z0-9_-]+$``, but our tool
# registry namespaces with a dot (``patients.search_patients``). Tool /
# module names are snake_case with no hyphens, so ``.`` <-> ``-`` is a
# lossless bijection confined to this provider.
def _uses_completion_tokens(model: str) -> bool:
    """GPT-5 and the o-series require `max_completion_tokens`, not `max_tokens`."""
    m = model.lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _to_openai_name(qualified: str) -> str:
    return qualified.replace(".", "-")


def _from_openai_name(safe: str) -> str:
    return safe.replace("-", ".")


def _sanitize_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function", {})
    return {**tool, "function": {**fn, "name": _to_openai_name(fn["name"])}}


def _parse_args(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _to_openai_messages(system: str, messages: list[ProviderMessage]) -> list[dict[str, Any]]:
    """Flatten neutral messages into OpenAI's wire shape.

    One neutral ``tool`` message with N result blocks expands into N
    OpenAI ``role:"tool"`` messages (one per ``tool_call_id``).
    """
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})

    for msg in messages:
        if msg.role is Role.USER:
            out.append({"role": "user", "content": _join_text(msg)})

        elif msg.role is Role.ASSISTANT:
            text = _join_text(msg)
            tool_calls = [
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": _to_openai_name(block.name),
                        "arguments": json.dumps(block.input),
                    },
                }
                for block in msg.content
                if isinstance(block, ToolUseBlock)
            ]
            wire: dict[str, Any] = {"role": "assistant", "content": text or None}
            if tool_calls:
                wire["tool_calls"] = tool_calls
            out.append(wire)

        elif msg.role is Role.TOOL:
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.tool_call_id,
                            "content": _stringify(block.content),
                        }
                    )

    return out


def _join_text(msg: ProviderMessage) -> str:
    return "".join(b.text for b in msg.content if isinstance(b, TextBlock))


def _stringify(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)
