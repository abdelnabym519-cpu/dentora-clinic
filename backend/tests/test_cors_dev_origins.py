"""CORS regression: the docker-compose dev frontend origin must be allowed.

Root cause being locked in: the compose dev stack serves the frontend on
``http://localhost:3100`` while the development convenience allowlist only
covered :3000/:3001 — so a fresh local stack's very first browser API call
(the ``/setup`` POST) was CORS-blocked: the backend processed and committed
the request, the browser blocked the response, and the setup wizard showed
a generic "try again" error on every retry (409s were blocked the same way).
"""

import pytest
from httpx import ASGITransport, AsyncClient

COMPOSE_DEV_ORIGIN = "http://localhost:3100"

# CORS preflights are answered by the middleware before routing, so no
# auth/db fixtures are needed — the bare client app is enough.
pytestmark = pytest.mark.asyncio


async def _preflight(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    return transport


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://localhost:3000",
    ],
)
async def test_dev_preflight_allows_compose_and_bare_frontend_origins(origin: str) -> None:
    """Preflight from the compose (:3100) and bare-dev (:3000) origins is allowed in development."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.options(
            "/api/v1/auth/setup",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


async def test_dev_preflight_still_rejects_unknown_origin() -> None:
    """An origin that is neither configured nor in the dev list gets no ACAO header."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.options(
            "/api/v1/auth/setup",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.headers.get("access-control-allow-origin") is None
