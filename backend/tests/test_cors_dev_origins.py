"""Regression: the Docker Compose frontend origin must pass CORS in dev.

The local stack publishes the frontend on host port 3100 ("3100:3000");
the development CORS fallback must therefore include that origin, or every
browser call (login, AI cards) is blocked before reaching the API.
"""

from fastapi.testclient import TestClient

from app.main import app

FRONTEND_ORIGIN = "http://localhost:3100"

client = TestClient(app)


def test_dev_cors_allows_the_published_frontend_origin() -> None:
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN


def test_dev_cors_still_allows_legacy_dev_ports() -> None:
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
