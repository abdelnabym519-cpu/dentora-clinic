"""End-to-end SSE fail-safety for the copilot chat path.

The streaming endpoint ``POST /api/v1/copilot/sessions/{id}/messages``
runs the *real* production chain: router -> ``drive_turn`` bridge ->
``run_turn`` orchestrator -> ``get_provider(conv.provider)``. No provider
is injected here, so when the deployment has no AI credential configured
the chain must surface a clean SSE ``error`` event — it must never emit a
fabricated assistant turn and must never crash with a 500 mid-stream.

This guards the clinical-safety rule: AI failure never becomes fake AI
output. The genuine model-inference path is covered (through the same
Provider abstraction, with a recording provider) in
``test_llm_orchestrator.py`` and ``test_copilot_bridge.py``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.config import settings
from app.database import engine


@pytest_asyncio.fixture(autouse=True)
async def _dispose_global_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def _sse_events(body: str) -> list[tuple[str, str]]:
    """Parse an SSE body into ``(event, data)`` pairs."""
    events: list[tuple[str, str]] = []
    event = "message"
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
        elif line == "":
            if data_lines:
                events.append((event, "".join(data_lines)))
            event = "message"
            data_lines = []
    return events


@pytest.mark.asyncio
async def test_chat_without_ai_credential_emits_error_not_fabricated_text(
    client: AsyncClient, auth_headers: dict, test_clinic, monkeypatch
) -> None:
    # Force the real provider factory down the "no credential" path for
    # the default openai provider regardless of ambient env.
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LICENSE_ENFORCEMENT", False, raising=False)

    created = await client.post("/api/v1/copilot/sessions", headers=auth_headers, json={})
    assert created.status_code == 201, created.text
    session_id = created.json()["data"]["id"]

    async with client.stream(
        "POST",
        f"/api/v1/copilot/sessions/{session_id}/messages",
        headers=auth_headers,
        json={"content": "Hola, ¿qué citas tengo hoy?"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join([chunk async for chunk in response.aiter_text()])

    events = _sse_events(body)
    kinds = [name for name, _ in events]

    # The failure must be reported as an explicit error event...
    assert "error" in kinds, body
    error_data = next(data for name, data in events if name == "error")
    # ...it must name the missing provider/credential (no silent failure)...
    assert (
        "OPENAI_API_KEY" in error_data
        or "provider" in error_data.lower()
        or "ai" in error_data.lower()
    )

    # ...and crucially it must NOT contain a fabricated assistant turn:
    # no token frames and no terminal "done" frame would be faked.
    assert "token" not in kinds, "must not stream fabricated AI text"
    assert "done" not in kinds, "must not report a successful (faked) turn"


@pytest.mark.asyncio
async def test_chat_requires_chat_permission(client: AsyncClient, test_clinic) -> None:
    """A user with no clinic membership cannot open a copilot stream."""
    # No auth headers at all -> 401 from the auth dependency.
    async with client.stream(
        "POST",
        "/api/v1/copilot/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"content": "hi"},
    ) as response:
        assert response.status_code in (401, 403)
        await response.aread()
