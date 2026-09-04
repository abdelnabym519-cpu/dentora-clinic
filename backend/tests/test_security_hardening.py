"""Adversarial tests for SECURITY / LOAD VERIFICATION gaps G1–G5.

* G1 — per-account login throttle + constant-time unknown-email path.
* G2 — baseline security response headers on success AND error paths.
* G3 — ``Content-Disposition`` filename sanitization (header injection).
* G4 — storage-path extension sanitization (separators / length).
* G5 — refresh-token rotation with reuse detection (theft ⇒ revoke all).

SlowAPI limiters are disabled under ``TESTING=true``, so the 429s
asserted here can only come from the per-account throttle itself.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt

from app.config import settings
from app.core.auth.service import login_backoff_remaining
from app.modules.media.validation import content_disposition_filename, get_file_extension

_SETUP_PAYLOAD = {
    "admin_first_name": "Admin",
    "admin_last_name": "User",
    "admin_email": "admin@example.com",
    "admin_password": "SecurePass123",
    "clinic_name": "My Clinic",
    "clinic_tax_id": "B12345678",
}


async def _setup_and_login(client: AsyncClient) -> dict:
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD)
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@example.com", "password": "SecurePass123"},
    )
    assert response.status_code == 200
    return response.json()


async def _bad_login(client: AsyncClient, password: str = "WrongPass999"):
    return await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@example.com", "password": password},
    )


# ---------------------------------------------------------------------------
# G1 — login throttle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_throttles_after_repeated_failures(client: AsyncClient) -> None:
    """Five failures are free; the sixth attempt is rejected with 429."""
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD)

    for _ in range(5):
        response = await _bad_login(client)
        assert response.status_code == 401

    throttled = await _bad_login(client)
    assert throttled.status_code == 429
    assert throttled.headers.get("Retry-After") is not None
    # The global HTTPException handler stringifies dict details into the
    # standard ErrorResponse envelope (same as the trial_expired flow).
    body = throttled.json()
    assert "login_throttled" in body["message"]


@pytest.mark.asyncio
async def test_login_throttle_blocks_correct_password_until_backoff_expires(
    client: AsyncClient,
) -> None:
    """Waiting out the backoff is mandatory — even the right password 429s."""
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD)
    for _ in range(6):
        await _bad_login(client)

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@example.com", "password": "SecurePass123"},
    )
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_login_success_resets_throttle_counter(client: AsyncClient) -> None:
    """A success wipes prior failures: 4 + success + 5 more must not 429."""
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD)
    for _ in range(4):
        assert (await _bad_login(client)).status_code == 401

    ok = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@example.com", "password": "SecurePass123"},
    )
    assert ok.status_code == 200

    for _ in range(5):
        assert (await _bad_login(client)).status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_is_401_not_429(client: AsyncClient) -> None:
    """No account ⇒ no throttle row ⇒ always the identical 401."""
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD)
    for _ in range(7):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "ghost@example.com", "password": "Whatever123"},
        )
        assert response.status_code == 401


def test_login_backoff_decays_after_a_day() -> None:
    """Ancient failures do not haunt the account forever."""
    now = datetime.now(UTC)
    assert login_backoff_remaining(9, now - timedelta(days=2), now) == timedelta(0)
    assert login_backoff_remaining(5, now - timedelta(seconds=10), now) > timedelta(0)
    assert login_backoff_remaining(0, None, now) == timedelta(0)


# ---------------------------------------------------------------------------
# G5 — refresh rotation / reuse detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_rotation_replay_and_reuse(client: AsyncClient) -> None:
    """Rotate ⇒ raced retry succeeds idempotently ⇒ forked token revokes all."""
    tokens = await _setup_and_login(client)
    r1 = tokens["refresh_token"]

    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert first.status_code == 200
    r2 = first.json()["refresh_token"]
    assert r2 != r1

    # Raced retry with the just-superseded token: idempotent success.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert replay.status_code == 200

    # Rotate forward with the live token.
    second = await client.post("/api/v1/auth/refresh", json={"refresh_token": r2})
    assert second.status_code == 200
    r3 = second.json()["refresh_token"]

    # r1 is now long-superseded: reuse ⇒ theft ⇒ every session revoked.
    stolen = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert stolen.status_code == 401

    # Even the live token died with the family wipe.
    dead = await client.post("/api/v1/auth/refresh", json={"refresh_token": r3})
    assert dead.status_code == 401

    # Fresh login opens a new chain and works again.
    again = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@example.com", "password": "SecurePass123"},
    )
    assert again.status_code == 200


@pytest.mark.asyncio
async def test_refresh_adopts_legacy_token_without_jti(client: AsyncClient) -> None:
    """Pre-hardening refresh tokens (no ``jti``) are adopted, not bricked."""
    tokens = await _setup_and_login(client)
    legacy = jwt.encode(
        {
            "sub": jwt.decode(
                tokens["refresh_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )["sub"],
            "exp": datetime.now(UTC) + timedelta(days=7),
            "type": "refresh",
            "token_version": 0,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": legacy})
    assert response.status_code == 200
    adopted = response.json()["refresh_token"]
    assert jwt.decode(adopted, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]).get("jti")


# ---------------------------------------------------------------------------
# G2 — security headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_headers_on_success_and_errors(client: AsyncClient) -> None:
    """Hardening headers ride every response, including error paths."""
    for response in (
        await client.get("/health"),
        await client.get("/api/v1/auth/setup/status"),
        await client.get("/api/v1/does-not-exist"),
    ):
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Referrer-Policy") == "same-origin"


# ---------------------------------------------------------------------------
# G3 — Content-Disposition sanitization
# ---------------------------------------------------------------------------


def test_content_disposition_strips_header_breakout() -> None:
    """Quotes, backslashes and CR/LF cannot escape the filename parameter."""
    header = content_disposition_filename('x";\r\nX-Injected: 1\\.pdf')
    assert "\r" not in header and "\n" not in header and '\\"' not in header
    assert header.startswith("attachment;")
    assert 'filename="x;X-Injected: 1.pdf"' in header


def test_content_disposition_preserves_unicode_via_rfc5987() -> None:
    """Spanish filenames keep their real name through ``filename*``."""
    header = content_disposition_filename("presupuesto niño — 2026.pdf")
    assert "filename*=" in header
    assert "\n" not in header


# ---------------------------------------------------------------------------
# G4 — extension sanitization
# ---------------------------------------------------------------------------


def test_get_file_extension_sanitizes() -> None:
    """Only short ``[a-z0-9]`` survives; separators and length are cut."""
    assert get_file_extension("photo.JPG") == "jpg"
    assert get_file_extension("scan.tar.gz") == "gz"
    assert get_file_extension("noext") == ""
    assert get_file_extension("evil.../..\\x") == "x"
    assert get_file_extension("a.b/c") == "bc"
    assert len(get_file_extension("a." + "p" * 200)) <= 10
    assert get_file_extension("a.pd f!") == "pdf"
